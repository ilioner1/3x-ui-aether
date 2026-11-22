package controller

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/web/middleware"
)

const salesTokenEnv = "XUI_DELEGATED_SALES_TOKEN"

var salesOrderReference = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`)

func salesTokenHash(db *gorm.DB) (string, error) {
	var config model.DelegatedSalesConfig
	err := db.Select("token_managed", "token_hash").First(&config, 1).Error
	if err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
		return "", err
	}
	if config.TokenManaged {
		return config.TokenHash, nil
	}
	if token := os.Getenv(salesTokenEnv); len(token) >= 32 {
		hash := sha256.Sum256([]byte(token))
		return hex.EncodeToString(hash[:]), nil
	}
	return "", nil
}

func isDelegatedSalesBearer(header string) bool {
	candidate, ok := strings.CutPrefix(header, "Bearer ")
	if !ok || len(candidate) < 32 {
		return false
	}
	want, err := salesTokenHash(database.GetDB())
	hash := sha256.Sum256([]byte(candidate))
	return err == nil && subtle.ConstantTimeCompare([]byte(hex.EncodeToString(hash[:])), []byte(want)) == 1
}

func (a *delegatedController) salesTokenStatus(c *gin.Context) {
	c.Header("Cache-Control", "no-store")
	hash, err := salesTokenHash(database.GetDB())
	if err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read the sales token status.")
		return
	}
	jsonObj(c, gin.H{"active": hash != ""}, nil)
}

func (a *delegatedController) changeSalesToken(c *gin.Context) {
	c.Header("Cache-Control", "no-store")
	var token, tokenHash string
	switch c.PostForm("action") {
	case "generate":
		var random [32]byte
		if _, err := rand.Read(random[:]); err != nil {
			pureJsonMsg(c, http.StatusInternalServerError, false, "Could not generate a sales token.")
			return
		}
		token = hex.EncodeToString(random[:])
		hash := sha256.Sum256([]byte(token))
		tokenHash = hex.EncodeToString(hash[:])
	case "revoke":
	default:
		pureJsonMsg(c, http.StatusBadRequest, false, "Invalid token action.")
		return
	}
	config := model.DelegatedSalesConfig{ID: 1, TokenManaged: true, TokenHash: tokenHash}
	if err := database.GetDB().Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "id"}},
		DoUpdates: clause.AssignmentColumns([]string{"token_managed", "token_hash"}),
	}).Create(&config).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not save the sales token.")
		return
	}
	jsonObj(c, gin.H{"active": token != "", "token": token}, nil)
}

func (a *delegatedController) registerSalesAPI(g *gin.RouterGroup) {
	api := g.Group("/delegate-sales/v1")
	api.Use(func(c *gin.Context) {
		if !isDelegatedSalesBearer(c.GetHeader("Authorization")) {
			c.AbortWithStatus(http.StatusUnauthorized)
			return
		}
		c.Header("Cache-Control", "no-store")
		c.Set("delegated_sales_api", true)
	})
	api.GET("/catalog", a.salesCatalog)
	api.GET("/trial-settings", a.trialSettings)
	api.PUT("/trial-settings", middleware.MaxBodyBytes(4096), a.saveTrialSettings)
	api.POST("/trials", middleware.MaxBodyBytes(4096), a.issueTrial)
	api.PUT("/settings", middleware.MaxBodyBytes(4096), a.saveSalesSettings)
	api.POST("/plans", middleware.MaxBodyBytes(4096), a.saveSalesPlan)
	api.POST("/orders", middleware.MaxBodyBytes(4096), a.createSalesOrder)
	api.GET("/accounts", a.salesAccounts)
	api.PUT("/accounts/:id/quota", middleware.MaxBodyBytes(4096), a.setSalesQuota)
}

type salesCatalogView struct {
	Plans   []model.DelegatedSalesPlan `json:"plans"`
	Groups  []model.DelegatedGroup     `json:"groups"`
	GroupID int64                      `json:"groupId"`
}

func (a *delegatedController) salesCatalog(c *gin.Context) {
	db := database.GetDB()
	view := salesCatalogView{
		Plans: []model.DelegatedSalesPlan{}, Groups: []model.DelegatedGroup{},
	}
	var config model.DelegatedSalesConfig
	if err := db.First(&config, 1).Error; err != nil && !errors.Is(err, gorm.ErrRecordNotFound) {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read sales settings.")
		return
	}
	view.GroupID = config.GroupID
	if err := db.Order("id").Find(&view.Groups).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read inbound groups.")
		return
	}
	plans := db.Order("quota_gib, id")
	if c.GetBool("delegated_sales_api") {
		plans = plans.Where("enabled = ?", true)
	}
	if err := plans.Find(&view.Plans).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read sales plans.")
		return
	}
	jsonObj(c, view, nil)
}

func (a *delegatedController) saveSalesPlan(c *gin.Context) {
	id := delegateID(c.PostForm("id"))
	name := delegateName(c.PostForm("name"), 100)
	quota := delegateID(c.PostForm("quotaGiB"))
	if name == "" || quota < 100 || quota > 1_000_000 {
		pureJsonMsg(c, http.StatusBadRequest, false, "Enter a name and a quota of at least 100 GiB.")
		return
	}
	db := database.GetDB()
	enabled := c.PostForm("enabled") == "1"
	if id == 0 {
		plan := model.DelegatedSalesPlan{Name: name, QuotaGiB: quota, Enabled: enabled}
		if err := db.Create(&plan).Error; err != nil {
			pureJsonMsg(c, http.StatusInternalServerError, false, "Could not create the sales plan.")
			return
		}
		id = plan.ID
	} else {
		result := db.Model(&model.DelegatedSalesPlan{}).Where("id = ?", id).
			Updates(map[string]any{"name": name, "quota_gib": quota, "enabled": enabled})
		if result.Error != nil {
			pureJsonMsg(c, http.StatusInternalServerError, false, "Could not update the sales plan.")
			return
		}
		if result.RowsAffected == 0 {
			pureJsonMsg(c, http.StatusNotFound, false, "Sales plan not found.")
			return
		}
	}
	jsonObj(c, gin.H{"id": id}, nil)
}

func (a *delegatedController) saveSalesSettings(c *gin.Context) {
	var body struct {
		GroupID int64 `json:"groupId"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || body.GroupID <= 0 {
		pureJsonMsg(c, http.StatusBadRequest, false, "Choose a delegated inbound group.")
		return
	}
	db := database.GetDB()
	var available int64
	if err := allowedDelegatedInbounds(db, body.GroupID).Count(&available).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read the inbound group.")
		return
	}
	if available == 0 {
		pureJsonMsg(c, http.StatusBadRequest, false, "The group needs an active inbound.")
		return
	}
	config := model.DelegatedSalesConfig{ID: 1, GroupID: body.GroupID}
	if err := db.Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "id"}},
		DoUpdates: clause.AssignmentColumns([]string{"group_id"}),
	}).Create(&config).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not save sales settings.")
		return
	}
	jsonObj(c, nil, nil)
}

var (
	errSalesOrderConflict   = errors.New("order reference already used")
	errSalesPlanUnavailable = errors.New("sales plan or group unavailable")
)

type salesOrderRequest struct {
	Reference string `json:"reference"`
	PlanID    int64  `json:"planId"`
	QuotaGiB  int64  `json:"quotaGiB"`
	GroupID   int64  `json:"groupId"`
	Password  string `json:"password"`
}

func provisionSalesAccount(db *gorm.DB, request salesOrderRequest) (model.DelegatedAdmin, error) {
	var admin model.DelegatedAdmin
	hash, err := bcrypt.GenerateFromPassword([]byte(request.Password), bcrypt.DefaultCost)
	if err != nil {
		return admin, err
	}
	err = db.Transaction(func(tx *gorm.DB) error {
		order := model.DelegatedSalesOrder{Reference: request.Reference, PlanID: request.PlanID, QuotaGiB: request.QuotaGiB}
		reserved := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&order)
		if reserved.Error != nil {
			return reserved.Error
		}
		if reserved.RowsAffected == 0 {
			if err := tx.First(&order, "reference = ?", request.Reference).Error; err != nil {
				return err
			}
			if order.PlanID != request.PlanID || order.QuotaGiB != request.QuotaGiB {
				return errSalesOrderConflict
			}
			if err := tx.First(&admin, order.AdminID).Error; err != nil {
				return err
			}
			if request.GroupID != 0 && admin.GroupID != request.GroupID {
				return errSalesOrderConflict
			}
			if bcrypt.CompareHashAndPassword([]byte(admin.PasswordHash), []byte(request.Password)) != nil {
				return errSalesOrderConflict
			}
			return nil
		}

		var plan model.DelegatedSalesPlan
		if err := tx.Where("enabled = ? AND quota_gib = ?", true, request.QuotaGiB).First(&plan, request.PlanID).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return errSalesPlanUnavailable
			}
			return err
		}
		var config model.DelegatedSalesConfig
		if err := tx.First(&config, 1).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return errSalesPlanUnavailable
			}
			return err
		}
		if request.GroupID != 0 && request.GroupID != config.GroupID {
			return errSalesPlanUnavailable
		}
		var available int64
		if err := allowedDelegatedInbounds(tx, config.GroupID).Count(&available).Error; err != nil {
			return err
		}
		if available == 0 {
			return errSalesPlanUnavailable
		}
		digest := sha256.Sum256([]byte(request.Reference))
		admin = model.DelegatedAdmin{
			Username:     "sale-" + hex.EncodeToString(digest[:12]),
			PasswordHash: string(hash),
			GroupID:      config.GroupID,
			Enabled:      true,
			QuotaBytes:   plan.QuotaGiB * delegateGiB,
		}
		if err := tx.Create(&admin).Error; err != nil {
			return err
		}
		return tx.Model(&order).UpdateColumn("admin_id", admin.ID).Error
	})
	return admin, err
}

func (a *delegatedController) createSalesOrder(c *gin.Context) {
	var request salesOrderRequest
	if err := c.ShouldBindJSON(&request); err != nil || request.PlanID <= 0 ||
		request.QuotaGiB < 100 || request.QuotaGiB > 1_000_000 || request.GroupID < 0 ||
		!salesOrderReference.MatchString(request.Reference) ||
		len(request.Password) < 16 || len(request.Password) > 72 {
		pureJsonMsg(c, http.StatusBadRequest, false, "Invalid order reference, plan, quota or password.")
		return
	}
	admin, err := provisionSalesAccount(database.GetDB(), request)
	switch {
	case errors.Is(err, errSalesOrderConflict), errors.Is(err, errSalesPlanUnavailable):
		pureJsonMsg(c, http.StatusConflict, false, err.Error())
	case err != nil:
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not provision the delegated account.")
	default:
		jsonObj(c, gin.H{
			"id": admin.ID, "username": admin.Username, "quotaGiB": admin.QuotaBytes / delegateGiB,
			"groupId":   admin.GroupID,
			"loginPath": c.GetString("base_path") + "delegate/?account=" + url.QueryEscape(admin.Username),
		}, nil)
	}
}

func (a *delegatedController) salesAccounts(c *gin.Context) {
	accounts := []delegatedAccountSummary{}
	db := database.GetDB()
	if err := db.Model(&model.DelegatedAdmin{}).
		Select("id", "username", "group_id", "enabled", "quota_bytes", "used_bytes").
		Where("id > ?", delegateID(c.Query("after"))).
		Order("id").Limit(100).Find(&accounts).Error; err != nil {
		pureJsonMsg(c, http.StatusInternalServerError, false, "Could not read delegated accounts.")
		return
	}
	jsonObj(c, accounts, nil)
}

func (a *delegatedController) setSalesQuota(c *gin.Context) {
	var body struct {
		ExpectedQuotaGiB int64 `json:"expectedQuotaGiB"`
		QuotaGiB         int64 `json:"quotaGiB"`
	}
	id := delegateID(c.Param("id"))
	if err := c.ShouldBindJSON(&body); err != nil || id == 0 ||
		body.ExpectedQuotaGiB < 1 || body.ExpectedQuotaGiB > 1_000_000 ||
		body.QuotaGiB < 1 || body.QuotaGiB > 1_000_000 {
		pureJsonMsg(c, http.StatusBadRequest, false, "Invalid delegated account or quota.")
		return
	}
	var admin model.DelegatedAdmin
	if err := database.GetDB().Transaction(func(tx *gorm.DB) error {
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&admin, id).Error; err != nil {
			return err
		}
		if admin.QuotaBytes != body.ExpectedQuotaGiB*delegateGiB {
			return errSalesOrderConflict
		}
		admin.QuotaBytes = body.QuotaGiB * delegateGiB
		return tx.Model(&admin).UpdateColumn("quota_bytes", admin.QuotaBytes).Error
	}); err != nil {
		switch {
		case errors.Is(err, gorm.ErrRecordNotFound):
			pureJsonMsg(c, http.StatusNotFound, false, "Delegated account not found.")
		case errors.Is(err, errSalesOrderConflict):
			pureJsonMsg(c, http.StatusConflict, false, "The quota changed. Refresh before updating.")
		default:
			pureJsonMsg(c, http.StatusInternalServerError, false, "Could not update the quota.")
		}
		return
	}
	if admin.QuotaBytes <= admin.UsedBytes {
		a.xray.ScheduleDelegatedDisconnect()
	} else {
		a.xray.SetToNeedReconcile()
	}
	jsonObj(c, gin.H{"id": id, "quotaGiB": body.QuotaGiB, "usedBytes": admin.UsedBytes}, nil)
}
