package model

type DelegatedSalesPlan struct {
	ID       int64  `gorm:"primaryKey" json:"id"`
	Name     string `gorm:"size:100;not null" json:"name"`
	QuotaGiB  int64  `gorm:"column:quota_gib;not null" json:"quotaGiB"`
	Enabled  bool   `gorm:"not null" json:"enabled"`
}

type DelegatedSalesConfig struct {
	ID           int64  `gorm:"primaryKey;autoIncrement:false"`
	GroupID      int64  `gorm:"not null"`
	TokenManaged bool   `gorm:"not null;default:false" json:"-"`
	TokenHash    string `gorm:"size:64;not null;default:''" json:"-"`
}

type DelegatedSalesOrder struct {
	Reference string `gorm:"primaryKey;size:128"`
	PlanID     int64   `gorm:"not null"`
	QuotaGiB   int64  `gorm:"column:quota_gib;not null"`
	AdminID    int64  `gorm:"not null"`
}
