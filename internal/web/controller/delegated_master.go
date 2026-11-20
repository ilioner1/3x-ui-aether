package controller

import (
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/delegation"
)

type delegatedAccountSummary struct {
	ID         int64  `json:"id"`
	Username   string `json:"username"`
	GroupID    int64  `json:"groupId"`
	Enabled    bool   `json:"enabled"`
	QuotaBytes int64  `json:"quotaBytes"`
	UsedBytes  int64  `json:"usedBytes"`
}

func (a *delegatedController) adminData(c *gin.Context) {
	db := database.GetDB()
	accounts := []delegatedAccountSummary{}
	groups := []model.DelegatedGroup{}
	grants := []model.DelegatedInboundGrant{}
	inbounds := []model.Inbound{}
	if err := db.Model(&model.DelegatedAdmin{}).
		Select("id", "username", "group_id", "enabled", "quota_bytes", "used_bytes").
		Order("id").Find(&accounts).Error; err != nil {
		jsonObj(c, nil, err)
		return
	}
	if err := db.Order("id").Find(&groups).Error; err != nil {
		jsonObj(c, nil, err)
		return
	}
	if err := db.Find(&grants).Error; err != nil {
		jsonObj(c, nil, err)
		return
	}
	if err := delegation.EligibleInbounds(db).
		Select("inbounds.id", "inbounds.remark", "inbounds.protocol").Order("inbounds.id").Find(&inbounds).Error; err != nil {
		jsonObj(c, nil, err)
		return
	}
	jsonObj(c, gin.H{"accounts": accounts, "groups": groups, "grants": grants, "inbounds": inbounds}, nil)
}

func (a *delegatedController) resetAdminTraffic(c *gin.Context) {
	id := delegateID(c.PostForm("id"))
	if id == 0 {
		pureJsonMsg(c, http.StatusBadRequest, false, "Invalid admin.")
		return
	}
	res := database.GetDB().Model(&model.DelegatedAdmin{}).
		Where("id = ?", id).UpdateColumn("used_bytes", 0)
	if res.Error != nil {
		jsonObj(c, nil, res.Error)
		return
	}
	if res.RowsAffected == 0 {
		pureJsonMsg(c, http.StatusNotFound, false, "Admin not found.")
		return
	}
	a.xray.SetToNeedReconcile()
	jsonObj(c, nil, nil)
}
