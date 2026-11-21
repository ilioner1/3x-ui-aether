package controller

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-contrib/sessions"
	"github.com/gin-contrib/sessions/cookie"
	"github.com/gin-gonic/gin"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/dbtest"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
)

func TestDelegatedSalesProvisioningAndScope(t *testing.T) {
	const secret = "test-only-sales-token-not-for-deployment"
	t.Setenv(salesTokenEnv, secret)
	dbtest.InitDB(t, filepath.Join(t.TempDir(), "x-ui.db"))
	db := database.GetDB()
	group := model.DelegatedGroup{Name: "forosh"}
	plan := model.DelegatedSalesPlan{Name: "150 GiB", QuotaGiB: 150, Enabled: true}
	insert := func(row any) {
		t.Helper()
		if err := db.Create(row).Error; err != nil {
			t.Fatal(err)
		}
	}
	insert(&group)
	insert(&plan)
	inbound := model.Inbound{Remark: "sales-inbound", Protocol: model.VLESS, Port: 24443, Tag: "sales-local", Enable: true}
	insert(&inbound)
	insert(&model.DelegatedInboundGrant{GroupID: group.ID, InboundID: inbound.Id})

	router := gin.New()
	router.Use(func(c *gin.Context) { c.Set("base_path", "/base/") })
	(&delegatedController{}).registerSalesAPI(router.Group(""))
	router.GET("/master-api-check", (&APIController{}).checkAPIAuth, func(c *gin.Context) {
		c.Status(http.StatusNoContent)
	})
	call := func(method, path, token, body string) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		res := httptest.NewRecorder()
		router.ServeHTTP(res, req)
		return res
	}
	if res := call(http.MethodGet, "/delegate-sales/v1/catalog", "", ""); res.Code != http.StatusUnauthorized {
		t.Fatalf("the catalog accepted a missing token: %d", res.Code)
	}
	if res := call(http.MethodGet, "/master-api-check", secret, ""); res.Code != http.StatusUnauthorized {
		t.Fatalf("the master API accepted a sales token: %d", res.Code)
	}
	if res := call(http.MethodPut, "/delegate-sales/v1/settings", secret, fmt.Sprintf(`{"groupId":%d}`, group.ID)); res.Code != http.StatusOK {
		t.Fatalf("could not select a sales group: %s", res.Body.String())
	}
	if res := call(http.MethodPost, "/delegate-sales/v1/plans", "", ""); res.Code != http.StatusUnauthorized {
		t.Fatalf("plan creation accepted a missing token: %d", res.Code)
	}
	req := httptest.NewRequest(http.MethodPost, "/delegate-sales/v1/plans", strings.NewReader("name=200+GiB&quotaGiB=200&enabled=1"))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Authorization", "Bearer "+secret)
	planResponse := httptest.NewRecorder()
	router.ServeHTTP(planResponse, req)
	if planResponse.Code != http.StatusOK || !strings.Contains(planResponse.Body.String(), `"id":`) {
		t.Fatalf("the sales token could not create a plan: %d %s", planResponse.Code, planResponse.Body.String())
	}
	wrongGroup := fmt.Sprintf(`{"reference":"changed-group","planId":%d,"groupId":%d,"quotaGiB":150,"password":"test-password-56d6c"}`, plan.ID, group.ID+1)
	if res := call(http.MethodPost, "/delegate-sales/v1/orders", secret, wrongGroup); res.Code != http.StatusConflict {
		t.Fatalf("a changed group should require reviewing the order: %d", res.Code)
	}
	wrongPlanQuota := fmt.Sprintf(`{"reference":"stale-invoice","planId":%d,"quotaGiB":100,"password":"test-password-56d6c"}`, plan.ID)
	if res := call(http.MethodPost, "/delegate-sales/v1/orders", secret, wrongPlanQuota); res.Code != http.StatusConflict {
		t.Fatalf("a changed plan quota should require reviewing the order: %d", res.Code)
	}
	body := fmt.Sprintf(`{"reference":"paid-invoice-1","planId":%d,"quotaGiB":150,"password":"test-password-56d6c"}`, plan.ID)
	for i := 0; i < 2; i++ {
		res := call(http.MethodPost, "/delegate-sales/v1/orders", secret, body)
		if res.Code != http.StatusOK || !strings.Contains(res.Body.String(), `"quotaGiB":150`) ||
			!strings.Contains(res.Body.String(), "/base/delegate/?account=sale-") ||
			strings.Contains(res.Body.String(), "test-password") {
			t.Fatalf("order attempt %d: %d %s", i, res.Code, res.Body.String())
		}
	}
	res := call(http.MethodPost, "/delegate-sales/v1/orders", secret, strings.ReplaceAll(body, "test-password", "other-password"))
	if res.Code != http.StatusConflict {
		t.Fatalf("reusing a payment reference with different credentials returned %d", res.Code)
	}
	var admins []model.DelegatedAdmin
	if err := db.Find(&admins).Error; err != nil || len(admins) != 1 || admins[0].GroupID != group.ID {
		t.Fatalf("expected exactly one delegated account in its assigned group")
	}
	path := fmt.Sprintf("/delegate-sales/v1/accounts/%d/quota", admins[0].ID)
	res = call(http.MethodPut, path, secret, `{"expectedQuotaGiB":150,"quotaGiB":200}`)
	if res.Code != http.StatusOK {
		t.Fatalf("quota adjustment failed: %s", res.Body.String())
	}
	res = call(http.MethodPut, path, secret, `{"expectedQuotaGiB":150,"quotaGiB":200}`)
	if res.Code != http.StatusConflict {
		t.Fatalf("a stale quota adjustment overwrote the current plan: %d", res.Code)
	}
}

func TestDelegatedSalesTokenLifecycle(t *testing.T) {
	const legacy = "test-only-sales-token-not-for-deployment"
	t.Setenv(salesTokenEnv, legacy)
	dbtest.InitDB(t, filepath.Join(t.TempDir(), "x-ui.db"))
	db := database.GetDB()
	controller := &delegatedController{}
	router := gin.New()
	router.Use(sessions.Sessions("sales-test", cookie.NewStore([]byte("test-only-session-key-32-letters!"))))
	controller.register(router.Group(""))
	// Call the mutation handler with a fixture context only after testing the mounted auth guard.
	req := httptest.NewRequest(http.MethodPost, "/panel/delegated-admins/sales/token", nil)
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, req)
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("token management accepted an unauthenticated request: %d", unauthorized.Code)
	}
	change := func(action string) string {
		t.Helper()
		res := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(res)
		c.Request = httptest.NewRequest(http.MethodPost, "/", strings.NewReader("action="+action))
		c.Request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		controller.changeSalesToken(c)
		var payload struct {
			Obj struct {
				Token string
			}
		}
		if res.Code != http.StatusOK || res.Header().Get("Cache-Control") != "no-store" {
			t.Fatalf("token action %q failed: %d %s", action, res.Code, res.Body.String())
		}
		if err := json.Unmarshal(res.Body.Bytes(), &payload); err != nil {
			t.Fatal(err)
		}
		return payload.Obj.Token
	}
	if !isDelegatedSalesBearer("Bearer " + legacy) {
		t.Fatal("existing sales integration stopped before rotation")
	}
	first := change("generate")
	if len(first) != 64 || !isDelegatedSalesBearer("Bearer "+first) || isDelegatedSalesBearer("Bearer "+legacy) {
		t.Fatal("generated token did not replace the environment token")
	}
	var config model.DelegatedSalesConfig
	if err := db.First(&config, 1).Error; err != nil {
		t.Fatal(err)
	}
	if len(config.TokenHash) != 64 || config.TokenHash == first {
		t.Fatal("the token was stored without hashing")
	}
	second := change("generate")
	if second == first || !isDelegatedSalesBearer("Bearer "+second) || isDelegatedSalesBearer("Bearer "+first) {
		t.Fatal("rotation did not replace the old token")
	}
	change("revoke")
	if isDelegatedSalesBearer("Bearer "+second) || isDelegatedSalesBearer("Bearer "+legacy) {
		t.Fatal("revocation left a token active")
	}
}
