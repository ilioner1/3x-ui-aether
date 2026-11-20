package controller

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/gin-contrib/sessions"
	"github.com/gin-contrib/sessions/cookie"
	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/dbtest"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/delegation"
	"github.com/mhsanaei/3x-ui/v3/internal/web/session"
	"github.com/mhsanaei/3x-ui/v3/internal/xray"
)

func TestDelegatedAccountIsolationAndQuota(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dir)
	dbtest.InitDB(t, filepath.Join(dir, "x-ui.db"))
	db := database.GetDB()
	create := func(value any) {
		t.Helper()
		if err := db.Create(value).Error; err != nil {
			t.Fatal(err)
		}
	}
	group := model.DelegatedGroup{Name: "Example group"}
	create(&group)
	hash, err := bcrypt.GenerateFromPassword([]byte("test-password"), bcrypt.MinCost)
	if err != nil {
		t.Fatal(err)
	}
	first := model.DelegatedAdmin{Username: "first-delegate", PasswordHash: string(hash), Enabled: true, GroupID: group.ID, QuotaBytes: 100}
	second := model.DelegatedAdmin{Username: "second-delegate", PasswordHash: string(hash), Enabled: true, GroupID: group.ID, QuotaBytes: 100}
	create(&first)
	create(&second)
	f := model.ClientRecord{Email: "first-delegate-test", Enable: true}
	g := model.ClientRecord{Email: "second-delegate-test", Enable: true}
	create(&f)
	create(&g)
	fc := model.DelegatedClient{ClientID: &f.Id, AdminID: first.ID, InitialEmail: f.Email, Label: "FIRST-PRIVATE"}
	gc := model.DelegatedClient{ClientID: &g.Id, AdminID: second.ID, InitialEmail: g.Email, Label: "SECOND-PRIVATE"}
	create(&fc)
	create(&gc)
	create(&model.ClientInbound{ClientId: f.Id, InboundId: 100})
	create(&model.DelegatedInboundGrant{GroupID: group.ID, InboundID: 100})

	e := gin.New()
	e.Use(sessions.Sessions("delegate-test", cookie.NewStore([]byte("delegated-integration-secret"))))
	e.Use(func(c *gin.Context) { c.Set("base_path", "/"); c.Next() })
	(&delegatedController{}).register(e.Group(""))
	e.GET("/test-token", (&XUIController{}).csrfToken)
	e.GET("/master-only-check", (&BaseController{}).checkLogin, func(c *gin.Context) { c.Status(http.StatusNoContent) })
	e.GET("/test-master", func(c *gin.Context) {
		var master model.User
		if db.First(&master).Error != nil || session.SetLoginUser(c, &master) != nil {
			c.Status(http.StatusInternalServerError)
			return
		}
		c.Status(http.StatusNoContent)
	})
	server := httptest.NewServer(e)
	defer server.Close()
	jar, _ := cookiejar.New(nil)
	web := &http.Client{Jar: jar, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	read := func(path string) (int, string) {
		t.Helper()
		r, err := web.Get(server.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		defer r.Body.Close()
		var out strings.Builder
		_, _ = io.Copy(&out, r.Body)
		return r.StatusCode, out.String()
	}
	send := func(path string, values url.Values) int {
		t.Helper()
		r, err := web.PostForm(server.URL+path, values)
		if err != nil {
			t.Fatal(err)
		}
		defer r.Body.Close()
		return r.StatusCode
	}
	_, tokenPage := read("/test-token")
	var token struct {
		Obj string `json:"obj"`
	}
	if err := json.Unmarshal([]byte(tokenPage), &token); err != nil || token.Obj == "" {
		t.Fatalf("test session token was not available: %v", err)
	}
	if status := send("/delegate/login", url.Values{
		"username": {"first-delegate"},
		"password": {"test-password"},
		"_csrf":    {token.Obj},
	}); status != http.StatusOK {
		t.Fatalf("delegate login status %d", status)
	}
	status, page := read("/delegate/api/clients/list/paged")
	if status != http.StatusOK || !strings.Contains(page, f.Email) || strings.Contains(page, g.Email) {
		t.Fatal("delegate API ownership isolation failed")
	}
	if status, _ := read("/master-only-check"); status == http.StatusNoContent {
		t.Fatal("delegate session was accepted as master")
	}
	if status, _ := read("/delegate/api/clients/get/" + g.Email); status != http.StatusNotFound {
		t.Fatalf("cross-account client lookup returned %d", status)
	}
	if status := send("/delegate/api/server/restartXrayService", nil); status != http.StatusNotFound {
		t.Fatalf("delegate could call restart route: %d", status)
	}
	_, tokenPage = read("/delegate/api/csrf-token")
	if err := json.Unmarshal([]byte(tokenPage), &token); err != nil || token.Obj == "" {
		t.Fatalf("delegate session token was not available: %v", err)
	}
	postClient := func(path, body string) (int, string) {
		t.Helper()
		req, err := http.NewRequest(http.MethodPost, server.URL+path, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("X-CSRF-Token", token.Obj)
		req.Header.Set("Content-Type", "application/json")
		res, err := web.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer res.Body.Close()
		payload, err := io.ReadAll(res.Body)
		if err != nil {
			t.Fatal(err)
		}
		return res.StatusCode, string(payload)
	}
	if status, _ := postClient("/delegate/api/clients/update/"+g.Email, `{"enable":false}`); status != http.StatusNotFound {
		t.Fatalf("cross-account client write returned %d", status)
	}
	if _, response := postClient("/delegate/api/clients/add", `{"client":{"comment":"not granted","enable":true},"inboundIds":[999]}`); !strings.Contains(response, `"success":false`) {
		t.Fatalf("ungranted create response: %s", response)
	}
	var count int64
	if err := db.Model(&model.DelegatedClient{}).Count(&count).Error; err != nil || count != 2 {
		t.Fatalf("ungranted create added a row: %d %v", count, err)
	}

	if err := db.Transaction(func(tx *gorm.DB) error {
		crossed, err := delegation.RecordTraffic(tx, []*xray.ClientTraffic{{Email: f.Email, Up: 60, Down: 40}})
		if err == nil && !crossed {
			t.Error("quota crossing not detected")
		}
		return err
	}); err != nil {
		t.Fatal(err)
	}
	blocked, err := delegation.BlockedClients(db)
	if err != nil || !blocked[100][f.Email] {
		t.Fatalf("quota did not block first account: %#v %v", blocked, err)
	}
	if err := db.Model(&first).UpdateColumn("quota_bytes", 200).Error; err != nil {
		t.Fatal(err)
	}
	blocked, err = delegation.BlockedClients(db)
	if err != nil || blocked[100][f.Email] {
		t.Fatalf("top-up did not release quota block: %#v %v", blocked, err)
	}

	if status, _ := read("/test-master"); status != http.StatusNoContent {
		t.Fatal("master test login failed")
	}
	_, page = read("/panel/delegated-admins")
	for _, username := range []string{first.Username, second.Username} {
		if !strings.Contains(page, `href="/delegate/?account=`+username+`"`) {
			t.Fatalf("master page is missing the personal login link for %s", username)
		}
	}
	_, page = read("/panel/delegated-reports?admin=" + strconv.FormatInt(second.ID, 10))
	if !strings.Contains(page, "SECOND-PRIVATE") || strings.Contains(page, "FIRST-PRIVATE") {
		t.Fatal("master report did not show the chosen account")
	}
}

func TestDelegatedLedgerAndReportsWithManyClients(t *testing.T) {
	dbtest.InitDB(t, filepath.Join(t.TempDir(), "x-ui.db"))
	db := database.GetDB()
	const perAdmin = 600
	accounts := []model.DelegatedAdmin{
		{Username: "many-clients-first", GroupID: 1, Enabled: true, QuotaBytes: perAdmin},
		{Username: "many-clients-second", GroupID: 1, Enabled: true, QuotaBytes: 2 * perAdmin},
	}
	if err := db.Create(&accounts).Error; err != nil {
		t.Fatal(err)
	}
	clients := make([]model.ClientRecord, 2*perAdmin)
	for i := range clients {
		clients[i] = model.ClientRecord{Email: fmt.Sprintf("report-client-%04d", i), Enable: true}
	}
	if err := db.CreateInBatches(&clients, 100).Error; err != nil {
		t.Fatal(err)
	}
	owners := make([]model.DelegatedClient, len(clients))
	traffic := make([]*xray.ClientTraffic, len(clients))
	for i, client := range clients {
		owners[i] = model.DelegatedClient{AdminID: accounts[i/perAdmin].ID, ClientID: &clients[i].Id, InitialEmail: client.Email, Label: client.Email}
		traffic[i] = &xray.ClientTraffic{Email: client.Email, Up: 1}
	}
	if err := db.CreateInBatches(&owners, 100).Error; err != nil {
		t.Fatal(err)
	}
	if err := db.Transaction(func(tx *gorm.DB) error {
		crossed, err := delegation.RecordTraffic(tx, traffic)
		if err == nil && !crossed {
			t.Error("quota crossing across traffic batches was missed")
		}
		return err
	}); err != nil {
		t.Fatal(err)
	}
	for _, account := range accounts {
		var ledger model.DelegatedAdmin
		if err := db.First(&ledger, account.ID).Error; err != nil {
			t.Fatal(err)
		}
		if ledger.UsedBytes != perAdmin {
			t.Fatalf("account %d recorded %d bytes, want %d", account.ID, ledger.UsedBytes, perAdmin)
		}

		var seen int
		var cursor int64
		for page := 0; page < perAdmin/delegatePageSize; page++ {
			ctx, _ := gin.CreateTestContext(httptest.NewRecorder())
			ctx.Request = httptest.NewRequest(http.MethodGet, fmt.Sprintf("/?after=%d", cursor), nil)
			var view delegatedView
			if err := (&delegatedController{}).readClients(ctx, &view, account.ID); err != nil {
				t.Fatal(err)
			}
			if len(view.Clients) != delegatePageSize {
				t.Fatalf("page %d returned %d clients", page, len(view.Clients))
			}
			for _, row := range view.Clients {
				if row.AdminID != account.ID || row.ID <= cursor || row.UsedBytes != 1 {
					t.Fatalf("page %d contains an invalid client entry: %+v", page, row)
				}
				cursor = row.ID
				seen++
			}
			if seen < perAdmin && view.Next != cursor || seen == perAdmin && view.Next != 0 {
				t.Fatalf("page %d returned unexpected next cursor %d", page, view.Next)
			}
		}
	}
}
