package delegation

import (
	"fmt"
	"maps"
	"slices"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/xray"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// RecordTraffic is called inside the same transaction as the Xray usage poll.
// Monthly client resets and deletions have no effect on the account ledger.
func RecordTraffic(tx *gorm.DB, traffic []*xray.ClientTraffic) (bool, error) {
	deltas := make(map[string]int64)
	for _, entry := range traffic {
		if entry != nil && entry.Email != "" && entry.Up >= 0 && entry.Down >= 0 && entry.Up+entry.Down > 0 {
			deltas[entry.Email] += entry.Up + entry.Down
		}
	}
	if len(deltas) == 0 {
		return false, nil
	}
	type owner struct {
		Email string
		ID int64
		AdminID int64
	}
	byAdmin := make(map[int64]int64)
	emailList := slices.Sorted(maps.Keys(deltas))
	for len(emailList) > 0 {
		size := min(len(emailList), 500)
		var owners []owner
		err := tx.Table("delegated_clients AS d").
			Select("d.id, d.admin_id, c.email").
			Joins("JOIN clients AS c ON c.id = d.client_id OR (d.client_id IS NULL AND c.email = d.initial_email)").
			Where("c.email IN ?", emailList[:size]).
			Order("d.id").
			Scan(&owners).Error
		if err != nil {
			return false, err
		}
		for _, o := range owners {
			delta := deltas[o.Email]
			if err := tx.Model(&model.DelegatedClient{}).Where("id = ?", o.ID).
				UpdateColumn("used_bytes", gorm.Expr(database.ClampedAddExpr("used_bytes"), delta)).Error; err != nil {
				return false, err
			}
			byAdmin[o.AdminID] += delta
		}
		emailList = emailList[size:]
	}
	var crossed bool
	for _, id := range slices.Sorted(maps.Keys(byAdmin)) {
		var admin model.DelegatedAdmin
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&admin, id).Error; err != nil {
			return false, err
		}
		delta := byAdmin[id]
		if err := tx.Model(&admin).UpdateColumn("used_bytes", gorm.Expr(database.ClampedAddExpr("used_bytes"), delta)).Error; err != nil {
			return false, err
		}
		crossed = crossed || (admin.Enabled && admin.UsedBytes < admin.QuotaBytes && delta >= admin.QuotaBytes-admin.UsedBytes)
	}
	return crossed, nil
}

type blockedClient struct {
	InboundID int
	Email string
}

func BlockedClients(tx *gorm.DB) (map[int]map[string]bool, error) {
	var rows []blockedClient
	err := tx.Table("delegated_clients AS d").
		Select("ci.inbound_id, c.email").
		Joins("JOIN delegated_admins AS a ON a.id = d.admin_id").
		Joins("JOIN clients AS c ON c.id = d.client_id OR (d.client_id IS NULL AND c.email = d.initial_email)").
		Joins("JOIN client_inbounds AS ci ON ci.client_id = c.id").
		Joins("LEFT JOIN delegated_inbound_grants AS g ON g.group_id = a.group_id AND g.inbound_id = ci.inbound_id").
		Where("a.enabled = ? OR a.used_bytes >= a.quota_bytes OR g.inbound_id IS NULL", false).
		Scan(&rows).Error
	if err != nil {
		return nil, fmt.Errorf("load delegated client restrictions: %w", err)
	}
	result := make(map[int]map[string]bool)
	for _, row := range rows {
		if result[row.InboundID] == nil {
			result[row.InboundID] = make(map[string]bool)
		}
		result[row.InboundID][row.Email] = true
	}
	return result, nil
}

func EligibleInbounds(tx *gorm.DB) *gorm.DB {
	return tx.Model(&model.Inbound{}).
		Where("inbounds.node_id IS NULL AND inbounds.protocol IN ?", []model.Protocol{model.VLESS, model.VMESS, model.Trojan, model.Shadowsocks, model.Hysteria})
}
