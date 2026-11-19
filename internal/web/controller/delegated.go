package controller

import (
	_ "embed"
	"errors"
	"fmt"
	"html/template"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-contrib/sessions"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/delegation"
	"github.com/mhsanaei/3x-ui/v3/internal/web/middleware"
	"github.com/mhsanaei/3x-ui/v3/internal/web/service"
	"github.com/mhsanaei/3x-ui/v3/internal/web/session"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const (
	delegateSessionID    = "delegateAccount"
	delegateSessionEpoch = "delegateEpoch"
	delegateGiB          = int64(1 << 30)
	delegatePageSize     = 50
)

//go:embed delegated.html
var delegatedHTML string

var delegatedPage = template.Must(template.New("delegated").Funcs(template.FuncMap{
	"gib": func(n int64) string { return strconv.FormatFloat(float64(n)/float64(delegateGiB), 'f', 2, 64) },
	"quota": func(n int64) int64 { return n / delegateGiB },
}).Parse(delegatedHTML))

type delegatedController struct {
	BaseController
	clients  service.ClientService
	inbounds service.InboundService
	xray     service.XrayService
}

type delegatedClientRow struct {
	TotalGB   int64
	ID        int64
	Label     string
	UsedBytes int64
	Email     string
	Enabled   bool
	AdminID   int64
}

type delegatedView struct {
	Base     string
	CSRF     string
	Page     string
	Username string
	Admin    model.DelegatedAdmin
	Admins   []model.DelegatedAdmin
	Groups   []model.DelegatedGroup
	Group    model.DelegatedGroup
	Inbounds []model.Inbound
	Granted  map[int]bool
	Clients  []delegatedClientRow
	Links    []string
	Selected int64
	Next     int64
	Error    string
	Request  string
}

func (a *delegatedController) register(g *gin.RouterGroup) {
	csrf := middleware.CSRFMiddleware(getRemoteIp)
	root := g.Group("/delegate")
	root.GET("/", a.portal)
	root.POST("/login", middleware.MaxBodyBytes(16<<10), csrf, a.login)
	root.POST("/logout", middleware.MaxBodyBytes(16<<10), csrf, a.logout)
	root.POST("/clients", middleware.MaxBodyBytes(16<<10), csrf, a.createClient)
	root.GET("/links/:id", a.links)
	master := g.Group("/panel")
	master.Use(a.checkLogin, csrf)
	master.GET("/delegated-admins", a.admins)
	master.POST("/delegated-admins/group", middleware.MaxBodyBytes(64<<10), a.saveGroup)
	master.POST("/delegated-admins/account", middleware.MaxBodyBytes(16<<10), a.saveAdmin)
	master.GET("/delegated-reports", a.reports)
	master.GET("/delegated-reports/links/:id", a.masterLinks)
	master.POST("/delegated-reports/client", middleware.MaxBodyBytes(16<<10), a.updateClient)
}

func (a *delegatedController) render(c *gin.Context, view delegatedView) {
	view.Base = c.GetString("base_path")
	token, err := session.EnsureCSRFToken(c)
	if err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	view.CSRF = token
	if view.Username == "" {
		if user := session.GetLoginUser(c); user != nil {
			view.Username = user.Username
		}
	}
	c.Header("Cache-Control", "no-store")
	c.Header("Content-Type", "text/html; charset=utf-8")
	if err := delegatedPage.Execute(c.Writer, view); err != nil {
		c.Abort()
	}
}

func delegateID(raw string) int64 {
	id, _ := strconv.ParseInt(raw, 10, 64)
	return max(0, id)
}

func delegateName(raw string, limit int) string {
	value := strings.TrimSpace(raw)
	if len(value) > limit {
		return ""
	}
	return value
}

func (a *delegatedController) current(c *gin.Context) (model.DelegatedAdmin, bool) {
	s := sessions.Default(c)
	id, _ := s.Get(delegateSessionID).(int64)
	epoch, _ := s.Get(delegateSessionEpoch).(int64)
	var admin model.DelegatedAdmin
	if id <= 0 {
		return admin, false
	}
	err := database.GetDB().Where("enabled = ? AND session_epoch = ?", true, epoch).First(&admin, id).Error
	return admin, err == nil
}

var delegatedDummyHash = []byte("$2a$10$7EqJtq98hPqEX7fNZaFWoOloIQk3HvmgHc8r.Z6oRjkZMKt4e4PCy")

func (a *delegatedController) login(c *gin.Context) {
	username := strings.ToLower(delegateName(c.PostForm("username"), 64))
	password := c.PostForm("password")
	remote := getRemoteIp(c)
	if _, allowed := defaultLoginLimiter.allow(remote, username); !allowed || username == "" || len(password) > 72 {
		a.render(c, delegatedView{Page: "login", Error: "ورود ناموفق بود."})
		return
	}
	var admin model.DelegatedAdmin
	err := database.GetDB().Where("username = ? AND enabled = ?", username, true).Take(&admin).Error
	hash := delegatedDummyHash
	if err == nil {
		hash = []byte(admin.PasswordHash)
	}
	valid := bcrypt.CompareHashAndPassword(hash, []byte(password)) == nil
	if err != nil || !valid {
		defaultLoginLimiter.registerFailure(remote, username)
		a.render(c, delegatedView{Page: "login", Error: "نام کاربری یا رمز معتبر نیست."})
		return
	}
	defaultLoginLimiter.registerSuccess(remote, username)
	s := sessions.Default(c)
	s.Clear()
	s.Set(delegateSessionID, admin.ID)
	s.Set(delegateSessionEpoch, admin.SessionEpoch)
	if err := s.Save(); err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	c.Redirect(http.StatusSeeOther, c.GetString("base_path")+"delegate/")
}

func (a *delegatedController) logout(c *gin.Context) {
	s := sessions.Default(c)
	s.Delete(delegateSessionID)
	s.Delete(delegateSessionEpoch)
	if err := s.Save(); err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	c.Redirect(http.StatusSeeOther, c.GetString("base_path")+"delegate/")
}

func scopedDelegatedClients(db *gorm.DB, adminID int64) *gorm.DB {
	q := db.Table("delegated_clients AS d").
		Select("d.id, d.label, d.used_bytes, c.email, c.total_gb, c.enable AS enabled, d.admin_id").
		Joins("JOIN clients AS c ON c.id = d.client_id OR (d.client_id IS NULL AND c.email = d.initial_email)")
	if adminID > 0 {
		q = q.Where("d.admin_id = ?", adminID)
	}
	return q
}

func (a *delegatedController) readClients(c *gin.Context, view *delegatedView, id int64) error {
	if id <= 0 {
		return nil
	}
	var rows []delegatedClientRow
	q := scopedDelegatedClients(database.GetDB(), id).
		Where("d.id > ?", delegateID(c.Query("after"))).Order("d.id").Limit(delegatePageSize + 1)
	if err := q.Scan(&rows).Error; err != nil {
		return err
	}
	if len(rows) > delegatePageSize {
		rows = rows[:delegatePageSize]
		view.Next = rows[len(rows)-1].ID
	}
	view.Clients = rows
	return nil
}

func (a *delegatedController) portal(c *gin.Context) {
	admin, ok := a.current(c)
	if !ok {
		a.render(c, delegatedView{Page: "login"})
		return
	}
	a.portalView(c, admin, "")
}

func allowedDelegatedInbounds(db *gorm.DB, groupID int64) *gorm.DB {
	return delegation.EligibleInbounds(db).
		Joins("JOIN delegated_inbound_grants AS g ON g.inbound_id = inbounds.id").
		Where("g.group_id = ? AND inbounds.enable = ?", groupID, true)
}

func (a *delegatedController) portalView(c *gin.Context, admin model.DelegatedAdmin, message string) {
	view := delegatedView{Page: "portal", Username: admin.Username, Admin: admin, Error: message, Request: uuid.NewString()}
	if err := allowedDelegatedInbounds(database.GetDB(), admin.GroupID).Select("inbounds.id", "inbounds.remark", "inbounds.protocol").Order("inbounds.id").Find(&view.Inbounds).Error; err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	if err := a.readClients(c, &view, admin.ID); err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	a.render(c, view)
}

func (a *delegatedController) createClient(c *gin.Context) {
	admin, ok := a.current(c)
	if !ok {
		c.Status(http.StatusUnauthorized)
		return
	}
	label := delegateName(c.PostForm("label"), 100)
	requestID, err := uuid.Parse(c.PostForm("request"))
	inbound := delegateID(c.PostForm("inbound"))
	if err != nil || label == "" || inbound <= 0 {
		a.portalView(c, admin, "نام و اینباند معتبر انتخاب کن.")
		return
	}
	db := database.GetDB()
	owner := model.DelegatedClient{AdminID: admin.ID, Label: label,
		InitialEmail: fmt.Sprintf("reseller-%d-%s", admin.ID, requestID.String())}
	err = db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("enabled = ? AND session_epoch = ?", true, admin.SessionEpoch).
			Take(&admin, admin.ID).Error; err != nil {
			return err
		}
		if admin.UsedBytes >= admin.QuotaBytes {
			return errors.New("account quota exhausted")
		}
		var allowed int64
		if err := allowedDelegatedInbounds(tx, admin.GroupID).Where("inbounds.id = ?", inbound).Count(&allowed).Error; err != nil {
			return err
		}
		if allowed != 1 {
			return errors.New("inbound not assigned")
		}
		return tx.Create(&owner).Error
	})
	if err != nil {
		a.portalView(c, admin, "ساخت کلاینت انجام نشد. دسترسی، حجم حساب یا تکراری بودن درخواست رو بررسی کن.")
		return
	}
	payload := service.ClientCreatePayload{
		Client: model.Client{Email: owner.InitialEmail, Enable: true, Comment: label},
		InboundIds: []int{int(inbound)},
	}
	restart, createErr := a.clients.Create(&a.inbounds, &payload)
	var record model.ClientRecord
	if err := db.Select("id").Where("email = ?", owner.InitialEmail).Take(&record).Error; err == nil {
		if err := db.Model(&owner).UpdateColumn("client_id", record.Id).Error; err != nil {
			createErr = err
		}
	} else if createErr == nil {
		createErr = errors.New("client ownership not finalized")
	}
	if restart {
		a.xray.SetToNeedRestart()
	}
	a.xray.SetToNeedReconcile()
	notifyClientsChanged()
	if createErr != nil {
		a.portalView(c, admin, "ساخت کلاینت کامل نشد. وضعیت فهرست رو بررسی کن.")
		return
	}
	c.Redirect(http.StatusSeeOther, c.GetString("base_path")+"delegate/")
}

func (a *delegatedController) renderLinks(c *gin.Context, adminID int64) {
	var client delegatedClientRow
	id := delegateID(c.Param("id"))
	q := scopedDelegatedClients(database.GetDB(), adminID).Where("d.id = ?", id).Scan(&client)
	if q.Error != nil || client.ID == 0 {
		c.Status(http.StatusNotFound)
		return
	}
	links, err := a.inbounds.GetAllClientLinks(resolveHost(c), client.Email)
	if err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	a.render(c, delegatedView{Page: "links", Links: links, Clients: []delegatedClientRow{client}})
}

func (a *delegatedController) links(c *gin.Context) {
	admin, ok := a.current(c)
	if !ok {
		c.Status(http.StatusUnauthorized)
		return
	}
	a.renderLinks(c, admin.ID)
}

func (a *delegatedController) masterLinks(c *gin.Context) { a.renderLinks(c, 0) }

func (a *delegatedController) admins(c *gin.Context) {
	a.adminsView(c, "")
}

func (a *delegatedController) adminsView(c *gin.Context, message string) {
	db := database.GetDB()
	view := delegatedView{Page: "admins", Error: message, Granted: make(map[int]bool)}
	if db.Order("id").Find(&view.Groups).Error != nil ||
		db.Omit("password_hash").Order("id").Find(&view.Admins).Error != nil ||
		delegation.EligibleInbounds(db).Select("inbounds.id", "inbounds.remark", "inbounds.protocol").Order("inbounds.id").Find(&view.Inbounds).Error != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	if id := delegateID(c.Query("group")); id > 0 {
		if db.First(&view.Group, id).Error != nil {
			c.Status(http.StatusNotFound)
			return
		}
		var grants []model.DelegatedInboundGrant
		if db.Where("group_id = ?", id).Find(&grants).Error != nil {
			c.Status(http.StatusInternalServerError)
			return
		}
		for _, grant := range grants {
			view.Granted[grant.InboundID] = true
		}
	}
	if id := delegateID(c.Query("admin")); id > 0 {
		if db.Omit("password_hash").First(&view.Admin, id).Error != nil {
			c.Status(http.StatusNotFound)
			return
		}
	}
	a.render(c, view)
}

func (a *delegatedController) saveGroup(c *gin.Context) {
	name := delegateName(c.PostForm("name"), 100)
	if name == "" {
		a.adminsView(c, "نام گروه رو وارد کن.")
		return
	}
	ids := make(map[int]bool)
	for _, raw := range c.PostFormArray("inbound") {
		if id := delegateID(raw); id > 0 {
			ids[int(id)] = true
		}
	}
	if len(ids) > 500 {
		a.adminsView(c, "حداکثر ۵۰۰ اینباند در یک گروه.")
		return
	}
	id := delegateID(c.PostForm("id"))
	err := database.GetDB().Transaction(func(tx *gorm.DB) error {
		group := model.DelegatedGroup{Name: name}
		if id == 0 {
			if err := tx.Create(&group).Error; err != nil {
				return err
			}
		} else {
			if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&group, id).Error; err != nil {
				return err
			}
			if err := tx.Model(&group).UpdateColumn("name", name).Error; err != nil {
				return err
			}
		}
		var requested []int
		for inbound := range ids {
			requested = append(requested, inbound)
		}
		if len(requested) > 0 {
			var count int64
			if err := delegation.EligibleInbounds(tx).Where("inbounds.id IN ?", requested).Count(&count).Error; err != nil {
				return err
			}
			if count != int64(len(requested)) {
				return errors.New("unsupported inbounds")
			}
		}
		if err := tx.Where("group_id = ?", group.ID).Delete(&model.DelegatedInboundGrant{}).Error; err != nil {
			return err
		}
		grants := make([]model.DelegatedInboundGrant, 0, len(requested))
		for _, inbound := range requested {
			grants = append(grants, model.DelegatedInboundGrant{GroupID: group.ID, InboundID: inbound})
		}
		if len(grants) == 0 {
			return nil
		}
		return tx.CreateInBatches(&grants, 100).Error
	})
	if err != nil {
		a.adminsView(c, "گروه ذخیره نشد. نام و اینباندها رو بررسی کن.")
		return
	}
	if id != 0 {
		a.xray.ScheduleDelegatedDisconnect()
	}
	c.Redirect(http.StatusSeeOther, c.GetString("base_path")+"panel/delegated-admins")
}

func (a *delegatedController) saveAdmin(c *gin.Context) {
	username := strings.ToLower(delegateName(c.PostForm("username"), 64))
	password := c.PostForm("password")
	id := delegateID(c.PostForm("id"))
	groupID := delegateID(c.PostForm("group"))
	quota := delegateID(c.PostForm("quota"))
	enabled := c.PostForm("enable") == "1"
	if username == "" || quota == 0 || quota > 1_000_000 || groupID == 0 ||
		((id == 0 || password != "") && (len(password) < 8 || len(password) > 72)) {
		a.adminsView(c, "نام کاربری، گروه، حجم مثبت و رمز ۸ تا ۷۲ بایتی وارد کن.")
		return
	}
	var hash []byte
	if password != "" {
		var err error
		hash, err = bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
		if err != nil {
			c.Status(http.StatusInternalServerError)
			return
		}
	}
	var revoke bool
	err := database.GetDB().Transaction(func(tx *gorm.DB) error {
		var group model.DelegatedGroup
		if err := tx.First(&group, groupID).Error; err != nil {
			return err
		}
		if id == 0 {
			return tx.Create(&model.DelegatedAdmin{Username: username, PasswordHash: string(hash), GroupID: groupID,
				Enabled: enabled, QuotaBytes: quota * delegateGiB}).Error
		}
		var admin model.DelegatedAdmin
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&admin, id).Error; err != nil {
			return err
		}
		revoke = !enabled || admin.GroupID != groupID || quota*delegateGiB <= admin.UsedBytes
		fields := map[string]any{"username": username, "group_id": groupID, "enabled": enabled, "quota_bytes": quota * delegateGiB}
		if password != "" {
			fields["password_hash"] = string(hash)
		}
		if password != "" || admin.Username != username || admin.Enabled != enabled {
			fields["session_epoch"] = admin.SessionEpoch + 1
		}
		return tx.Model(&admin).Updates(fields).Error
	})
	if err != nil {
		a.adminsView(c, "حساب ذخیره نشد. نام کاربری تکراری نباشه.")
		return
	}
	if revoke {
		a.xray.ScheduleDelegatedDisconnect()
	} else {
		a.xray.SetToNeedReconcile()
	}
	c.Redirect(http.StatusSeeOther, c.GetString("base_path")+"panel/delegated-admins")
}

func (a *delegatedController) reports(c *gin.Context) {
	db := database.GetDB()
	view := delegatedView{Page: "reports", Selected: delegateID(c.Query("admin"))}
	if db.Omit("password_hash").Order("id").Find(&view.Admins).Error != nil || a.readClients(c, &view, view.Selected) != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	a.render(c, view)
}

func (a *delegatedController) updateClient(c *gin.Context) {
	db := database.GetDB()
	var row delegatedClientRow
	q := scopedDelegatedClients(db, 0).Where("d.id = ?", delegateID(c.PostForm("id"))).Scan(&row)
	if q.Error != nil || row.ID == 0 {
		c.Status(http.StatusNotFound)
		return
	}
	if label := delegateName(c.PostForm("label"), 100); label != "" {
		if db.Model(&model.DelegatedClient{}).Where("id = ?", row.ID).UpdateColumn("label", label).Error != nil {
			c.Status(http.StatusInternalServerError)
			return
		}
	}
	enabled := c.PostForm("enable") == "1"
	if raw := c.PostForm("clientQuota"); raw != "" {
		quota, err := strconv.ParseInt(raw, 10, 64)
		if err != nil || quota < 0 || quota > 1_000_000 {
			c.String(http.StatusBadRequest, "حجم کلاینت معتبر نیست.")
			return
		}
		if quota*delegateGiB != row.TotalGB {
			restart, err := a.clients.ResetClientTrafficLimitByEmail(&a.inbounds, row.Email, int(quota))
			if restart {
				a.xray.SetToNeedRestart()
			}
			if err != nil {
				c.String(http.StatusConflict, "تغییر حجم کلاینت انجام نشد.")
				return
			}
		}
	}
	if row.Enabled != enabled || c.PostForm("clientQuota") != "" {
		changed, restart, err := a.clients.SetClientEnableByEmail(&a.inbounds, row.Email, enabled)
		if restart {
			a.xray.SetToNeedRestart()
		}
		if changed && !enabled {
			a.xray.ScheduleDelegatedDisconnect()
		}
		if err != nil {
			c.String(http.StatusConflict, "تغییر وضعیت کامل نشد.")
			return
		}
		notifyClientsChanged()
	}
	c.Redirect(http.StatusSeeOther, fmt.Sprintf("%spanel/delegated-reports?admin=%d", c.GetString("base_path"), row.AdminID))
}
