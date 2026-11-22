package controller

import (
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/web/service"
)

const trialAdminName = "reseller-bot-trials"
const trialBudget = 100 * delegateGiB

var errTrialUnavailable = errors.New("trial service unavailable")
var errTrialAlreadyUsed = errors.New("monthly trial already used")

func trialEmail(telegramID int64, now time.Time) string {
	return fmt.Sprintf("rs-trial-%d-%s", telegramID, now.UTC().Format("200601"))
}

func validTrialVolume(volume int64) bool { return volume >= 1 && volume <= 500 }

func trialVolume(config model.DelegatedSalesConfig) int64 {
	if validTrialVolume(config.TrialMiB) {
		return config.TrialMiB
	}
	return 150
}

func (a *delegatedController) trialSettings(c *gin.Context) {
	db := database.GetDB()
	var config model.DelegatedSalesConfig
	if err := db.First(&config, 1).Error; err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read trial settings.")
		return
	}
	view := gin.H{"volumeMiB": trialVolume(config), "adminName": trialAdminName, "quotaBytes": trialBudget, "usedBytes": 0}
	if config.TrialAdminID > 0 {
		var admin model.DelegatedAdmin
		if err := db.Select("id", "used_bytes", "quota_bytes").First(&admin, config.TrialAdminID).Error; err != nil {
			pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read the trial account.")
			return
		}
		view["usedBytes"] = admin.UsedBytes
		view["quotaBytes"] = admin.QuotaBytes
	}
	jsonObj(c, view, nil)
}

func (a *delegatedController) saveTrialSettings(c *gin.Context) {
	var body struct {
		Volume int64 `json:"volumeMiB"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || !validTrialVolume(body.Volume) {
		pureJsonMsg(c, http.StatusBadRequest, false, "Enter a trial volume between 1 and 500 MiB.")
		return
	}
	config := model.DelegatedSalesConfig{ID: 1, TrialMiB: body.Volume}
	if err := database.GetDB().Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "id"}},
		DoUpdates: clause.AssignmentColumns([]string{"trial_mib"}),
	}).Create(&config).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not save trial settings.")
		return
	}
	jsonObj(c, gin.H{"volumeMiB": body.Volume}, nil)
}

func reserveTrial(db *gorm.DB, email string) (model.DelegatedClient, []int, error) {
	var owner model.DelegatedClient
	var inbounds []int
	err := db.Transaction(func(tx *gorm.DB) error {
		var config model.DelegatedSalesConfig
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&config, 1).Error; err != nil {
			return err
		}
		var admin model.DelegatedAdmin
		if config.TrialAdminID == 0 {
			var count int64
			if err := allowedDelegatedInbounds(tx, config.GroupID).Count(&count).Error; err != nil {
				return err
			}
			if count == 0 {
				return errTrialUnavailable
			}
			// This account owns trial clients and does not need password login.
			admin = model.DelegatedAdmin{
				Username: trialAdminName, PasswordHash: "!", GroupID: config.GroupID,
				QuotaBytes: trialBudget, Enabled: true,
			}
			if err := tx.Create(&admin).Error; err != nil {
				return err
			}
			if err := tx.Model(&config).Update("trial_admin_id", admin.ID).Error; err != nil {
				return err
			}
		} else if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&admin, config.TrialAdminID).Error; err != nil {
			return err
		}
		if !admin.Enabled {
			return errTrialUnavailable
		}
		err := tx.Where("initial_email = ? AND admin_id = ?", email, admin.ID).Take(&owner).Error
		if err == nil && owner.ClientID != nil {
			return nil
		}
		if err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}
		quota := trialVolume(config) * (1 << 20)
		if owner.ID != 0 {
			quota = owner.TrialQuotaBytes
		}
		if admin.QuotaBytes-admin.UsedBytes < quota {
			return errTrialUnavailable
		}
		if err := allowedDelegatedInbounds(tx, admin.GroupID).Order("inbounds.id").
			Limit(maxDelegatedInbounds).Pluck("inbounds.id", &inbounds).Error; err != nil {
			return err
		}
		if len(inbounds) == 0 {
			return errTrialUnavailable
		}
		if owner.ID == 0 {
			owner = model.DelegatedClient{AdminID: admin.ID, InitialEmail: email, Label: "Monthly trial", TrialQuotaBytes: quota}
			return tx.Create(&owner).Error
		}
		return nil
	})
	return owner, inbounds, err
}

func (a *delegatedController) issueTrial(c *gin.Context) {
	var body struct {
		TelegramID int64 `json:"telegramId"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || body.TelegramID <= 0 {
		pureJsonMsg(c, http.StatusBadRequest, false, "Enter a valid Telegram account ID.")
		return
	}
	uri, err := (&service.SettingService{}).StandardSubscriptionURI(c.Request.Host)
	if err != nil || uri == "" {
		pureJsonMsg(c, http.StatusServiceUnavailable, false, "Subscription URL is not configured.")
		return
	}
	db := database.GetDB()
	owner, inbounds, err := reserveTrial(db, trialEmail(body.TelegramID, time.Now()))
	if err != nil {
		pureJsonMsg(c, http.StatusServiceUnavailable, false, "Trial account is temporarily unavailable.")
		return
	}
	subID, err := a.trialSubscription(db, owner, inbounds)
	if errors.Is(err, errTrialAlreadyUsed) {
		pureJsonMsg(c, http.StatusConflict, false, "Monthly trial already used.")
		return
	}
	if err != nil || subID == "" {
		pureJsonMsg(c, http.StatusServiceUnavailable, false, "Trial subscription is temporarily unavailable.")
		return
	}
	jsonObj(c, gin.H{
		"subscriptionUrl": uri + subID,
		"volumeMiB": owner.TrialQuotaBytes / (1 << 20),
	}, nil)
}

func (a *delegatedController) trialSubscription(db *gorm.DB, owner model.DelegatedClient, inbounds []int) (string, error) {
	var record model.ClientRecord
	if owner.ClientID != nil {
		err := db.Select("sub_id").Where("id = ? AND email = ?", *owner.ClientID, owner.InitialEmail).Take(&record).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", errTrialAlreadyUsed
		}
		return record.SubID, err
	}
	// Recover a client created just before a connection dropped or the panel restarted.
	err := db.Select("id", "sub_id").Where("email = ?", owner.InitialEmail).Take(&record).Error
	if err == nil {
		err = db.Model(&owner).UpdateColumn("client_id", record.Id).Error
		return record.SubID, err
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		return "", err
	}
	return a.provisionOwnedClient(owner, inbounds, owner.TrialQuotaBytes, true)
}
