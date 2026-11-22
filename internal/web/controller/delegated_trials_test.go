package controller

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/dbtest"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
)

func TestDelegatedTrialMonthlyQuota(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dir)
	dbtest.InitDB(t, filepath.Join(dir, "x-ui.db"))
	db := database.GetDB()
	insert := func(row any) {
		t.Helper()
		if err := db.Create(row).Error; err != nil {
			t.Fatal(err)
		}
	}
	group := model.DelegatedGroup{Name: "trial-test-group"}
	insert(&group)
	inbound := model.Inbound{
		Remark: "trial-test-vless", Protocol: model.VLESS, Port: 25443, Tag: "trial-test",
		Enable: true, Settings: "{\"clients\":[],\"decryption\":\"none\"}",
	}
	insert(&inbound)
	insert(&model.DelegatedInboundGrant{GroupID: group.ID, InboundID: inbound.Id})
	insert(&model.DelegatedSalesConfig{ID: 1, GroupID: group.ID})

	now := time.Date(2026, 11, 21, 0, 0, 0, 0, time.UTC)
	email := trialEmail(1234, now)
	first, inbounds, err := reserveTrial(db, email)
	if err != nil || first.TrialQuotaBytes != 150<<20 || len(inbounds) != 1 {
		t.Fatalf("could not reserve the 150 MiB trial: %+v %v", first, err)
	}
	var admin model.DelegatedAdmin
	if err := db.First(&admin, first.AdminID).Error; err != nil || admin.Username != trialAdminName ||
		admin.QuotaBytes != 100*delegateGiB || admin.GroupID != group.ID {
		t.Fatalf("incorrect dedicated trial account: %+v %v", admin, err)
	}

	client := model.ClientRecord{Email: email, SubID: "test-subscription", Enable: true}
	insert(&client)
	controller := &delegatedController{}
	if sub, err := controller.trialSubscription(db, first, inbounds); sub != client.SubID || err != nil {
		t.Fatalf("could not recover existing subscription: %q %v", sub, err)
	}
	if err := db.Model(&model.DelegatedSalesConfig{}).Where("id = ?", 1).Update("trial_mib", 500).Error; err != nil {
		t.Fatal(err)
	}
	repeat, inbounds, err := reserveTrial(db, email)
	if err != nil || repeat.ID != first.ID || repeat.TrialQuotaBytes != 150<<20 || repeat.ClientID == nil {
		t.Fatalf("duplicate request changed the monthly claim: %+v %v", repeat, err)
	}
	if sub, err := controller.trialSubscription(db, repeat, inbounds); sub != client.SubID || err != nil {
		t.Fatalf("repeat did not return the same subscription: %q %v", sub, err)
	}
	next, _, err := reserveTrial(db, trialEmail(1234, now.AddDate(0, 1, 0)))
	if err != nil || next.ID == first.ID || next.TrialQuotaBytes != 500<<20 || next.AdminID != first.AdminID {
		t.Fatalf("next month did not use the configured quota: %+v %v", next, err)
	}
	if validTrialVolume(0) || validTrialVolume(501) || !validTrialVolume(1) || !validTrialVolume(500) {
		t.Fatal("incorrect test volume bounds")
	}
}
