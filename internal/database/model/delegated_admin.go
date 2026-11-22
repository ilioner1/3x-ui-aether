package model

// Delegated accounts never share the master User table or its session.
type DelegatedAdmin struct {
	ID           int64  `gorm:"primaryKey"`
	Username     string `gorm:"size:64;uniqueIndex;not null"`
	PasswordHash string `gorm:"not null"`
	GroupID      int64  `gorm:"index;not null"`
	Enabled      bool   `gorm:"not null"`
	QuotaBytes   int64  `gorm:"not null"`
	UsedBytes    int64  `gorm:"not null"`
	SessionEpoch int64  `gorm:"not null"`
}

type DelegatedGroup struct {
	ID   int64  `gorm:"primaryKey"`
	Name string `gorm:"size:100;uniqueIndex;not null"`
}

type DelegatedInboundGrant struct {
	GroupID   int64 `gorm:"primaryKey;autoIncrement:false"`
	InboundID int   `gorm:"primaryKey;autoIncrement:false"`
}

// Keep the ledger even if the master deletes a client or resets Xray stats.
type DelegatedClient struct {
	ID              int64  `gorm:"primaryKey;index:idx_delegated_client_page,priority:2"`
	AdminID         int64  `gorm:"not null;index:idx_delegated_client_page,priority:1"`
	ClientID        *int   `gorm:"uniqueIndex"`
	InitialEmail    string `gorm:"uniqueIndex;not null"`
	TrialQuotaBytes int64  `gorm:"not null;default:0"`
	Label           string `gorm:"size:100;not null"`
	UsedBytes       int64  `gorm:"not null"`
}
