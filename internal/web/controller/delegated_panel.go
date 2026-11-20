package controller

import (
	"encoding/json"
	"net/http"
	"slices"

	"github.com/gin-gonic/gin"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/delegation"
	"github.com/mhsanaei/3x-ui/v3/internal/web/middleware"
	"github.com/mhsanaei/3x-ui/v3/internal/web/service"
)

func (a *delegatedController) registerPanel(root *gin.RouterGroup, csrf gin.HandlerFunc) {
	panel := root.Group("/panel")
	panel.GET("/", a.panel)
	panel.GET("/inbounds", a.panel)
	panel.GET("/clients", a.panel)

	api := root.Group("/api", a.requireDelegate, csrf)
	api.GET("/csrf-token", (&XUIController{}).csrfToken)
	api.GET("/server/status", (&ServerController{}).status)
	api.POST("/setting/defaultSettings", a.panelDefaults)
	api.GET("/inbounds/list/slim", a.panelInbounds)
	api.GET("/inbounds/options", a.panelInboundOptions)
	api.GET("/clients/list/paged", a.panelClients)
	api.GET("/clients/get", a.panelClient)
	api.GET("/clients/get/:email", a.panelClient)
	api.GET("/clients/subLinks/:subId", a.panelSubLinks)
	api.POST("/clients/add", middleware.MaxBodyBytes(16<<10), a.panelCreateClient)
	api.POST("/clients/update", middleware.MaxBodyBytes(16<<10), a.panelUpdateClient)
	api.POST("/clients/update/:email", middleware.MaxBodyBytes(16<<10), a.panelUpdateClient)
}

func (a *delegatedController) panel(c *gin.Context) {
	if _, ok := a.current(c); !ok {
		c.Redirect(http.StatusTemporaryRedirect, c.GetString("base_path")+"delegate/")
		return
	}
	c.Set("delegated_panel", true)
	serveDistPage(c, "index.html")
}

func (a *delegatedController) requireDelegate(c *gin.Context) {
	admin, ok := a.current(c)
	if !ok {
		c.AbortWithStatus(http.StatusUnauthorized)
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Set("delegated_admin", admin)
}

func panelDelegate(c *gin.Context) model.DelegatedAdmin {
	return c.MustGet("delegated_admin").(model.DelegatedAdmin)
}

func delegateInboundRows(admin model.DelegatedAdmin) ([]model.Inbound, error) {
	rows := []model.Inbound{}
	err := delegation.EligibleInbounds(database.GetDB()).
		Joins("JOIN delegated_inbound_grants AS g ON g.inbound_id = inbounds.id").
		Where("g.group_id = ?", admin.GroupID).
		Select("inbounds.id", "inbounds.remark", "inbounds.enable", "inbounds.port",
			"inbounds.protocol", "inbounds.tag", "inbounds.stream_settings").
		Order("inbounds.id").Find(&rows).Error
	return rows, err
}

type delegatedTransport struct {
	Network  string `json:"network"`
	Security string `json:"security"`
}

func delegatedStream(raw string) delegatedTransport {
	var stream delegatedTransport
	_ = json.Unmarshal([]byte(raw), &stream)
	return stream
}

func (a *delegatedController) panelInbounds(c *gin.Context) {
	rows, err := delegateInboundRows(panelDelegate(c))
	if err != nil {
		jsonObj(c, nil, err)
		return
	}
	for i := range rows {
		// Only transport labels are needed by the table. Keys, server settings
		// and other admins' users never enter this response.
		stream, _ := json.Marshal(delegatedStream(rows[i].StreamSettings))
		rows[i].StreamSettings = string(stream)
		rows[i].Settings = "{}"
		rows[i].Sniffing = "{}"
	}
	jsonObj(c, rows, nil)
}

func (a *delegatedController) panelInboundOptions(c *gin.Context) {
	rows, err := delegateInboundRows(panelDelegate(c))
	if err != nil {
		jsonObj(c, nil, err)
		return
	}
	options := make([]service.InboundOption, 0, len(rows))
	for _, row := range rows {
		stream := delegatedStream(row.StreamSettings)
		options = append(options, service.InboundOption{
			Id: row.Id, Remark: row.Remark, Tag: row.Tag, Protocol: string(row.Protocol),
			Port: row.Port, Enable: row.Enable, Network: stream.Network, Security: stream.Security,
		})
	}
	jsonObj(c, options, nil)
}

func (a *delegatedController) panelClients(c *gin.Context) {
	var params service.ClientPageParams
	if err := c.ShouldBindQuery(&params); err != nil {
		c.Status(http.StatusBadRequest)
		return
	}
	admin := panelDelegate(c)
	params.DelegatedAdminID = admin.ID
	resp, err := a.clients.ListPaged(&a.inbounds, nil, params)
	if err != nil {
		jsonObj(c, nil, err)
		return
	}
	rows, err := delegateInboundRows(admin)
	if err != nil {
		jsonObj(c, nil, err)
		return
	}
	allowed := make(map[int]bool, len(rows))
	for _, row := range rows {
		allowed[row.Id] = true
	}
	for i := range resp.Items {
		resp.Items[i].InboundIds = slices.DeleteFunc(resp.Items[i].InboundIds, func(id int) bool { return !allowed[id] })
	}
	jsonObj(c, resp, nil)
}

func (a *delegatedController) ownedRecord(c *gin.Context, email string) (*model.ClientRecord, bool) {
	var record model.ClientRecord
	err := database.GetDB().Table("clients").
		Joins("JOIN delegated_clients AS owner ON owner.client_id = clients.id").
		Where("owner.admin_id = ? AND clients.email = ?", panelDelegate(c).ID, email).
		Take(&record).Error
	if err != nil {
		c.Status(http.StatusNotFound)
		return nil, false
	}
	return &record, true
}

func (a *delegatedController) permittedClient(c *gin.Context, record *model.ClientRecord) bool {
	inbounds, err := a.clients.GetInboundIdsForRecord(record.Id)
	if err != nil {
		c.Status(http.StatusInternalServerError)
		return false
	}
	rows, err := delegateInboundRows(panelDelegate(c))
	if err != nil {
		c.Status(http.StatusInternalServerError)
		return false
	}
	allowed := make(map[int]bool, len(rows))
	for _, row := range rows {
		allowed[row.Id] = true
	}
	for _, id := range inbounds {
		if !allowed[id] {
			c.Status(http.StatusForbidden)
			return false
		}
	}
	return true
}

func (a *delegatedController) panelClient(c *gin.Context) {
	email, ok := clientEmailParam(c)
	if !ok {
		return
	}
	record, ok := a.ownedRecord(c, email)
	if !ok || !a.permittedClient(c, record) {
		return
	}
	payload, err := (&ClientController{}).buildClientPayload(record)
	jsonObj(c, payload, err)
}

func (a *delegatedController) panelSubLinks(c *gin.Context) {
	subID := c.Param("subId")
	records, err := a.clients.GetRecordsBySubID(subID)
	if err != nil || len(records) == 0 {
		c.Status(http.StatusNotFound)
		return
	}
	for _, record := range records {
		owned, ok := a.ownedRecord(c, record.Email)
		if !ok || !a.permittedClient(c, owned) {
			return
		}
	}
	(&ClientController{}).getSubLinks(c)
}

func (a *delegatedController) panelDefaults(c *gin.Context) {
	uri, err := (&service.SettingService{}).StandardSubscriptionURI(c.Request.Host)
	jsonObj(c, gin.H{"pageSize": 25, "subEnable": uri != "", "subURI": uri}, err)
}

const (
	maxDelegatedClientQuota = 1_000_000 * delegateGiB
	maxDelegatedInbounds    = 500
)

func (a *delegatedController) panelCreateClient(c *gin.Context) {
	var body struct {
		Client struct {
			Email   string `json:"email"`
			Comment string `json:"comment"`
			TotalGB int64  `json:"totalGB"`
			Enable  bool   `json:"enable"`
		} `json:"client"`
		InboundIDs []int `json:"inboundIds"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || len(body.InboundIDs) == 0 ||
		body.Client.TotalGB < 0 || body.Client.TotalGB > maxDelegatedClientQuota {
		pureJsonMsg(c, http.StatusBadRequest, false, "Select at least one inbound and enter a valid client quota.")
		return
	}
	label := delegateName(body.Client.Comment, 100)
	if label == "" {
		label = delegateName(body.Client.Email, 100)
	}
	if label == "" {
		pureJsonMsg(c, http.StatusBadRequest, false, "Enter a client name.")
		return
	}
	subID, err := a.addOwnedClient(panelDelegate(c), body.InboundIDs, label, body.Client.TotalGB, body.Client.Enable)
	if err != nil {
		jsonObj(c, nil, err)
		return
	}
	uri, _ := (&service.SettingService{}).StandardSubscriptionURI(c.Request.Host)
	if uri != "" && subID != "" {
		jsonObj(c, gin.H{"subscriptionUrl": uri + subID}, nil)
		return
	}
	jsonObj(c, nil, nil)
}

func (a *delegatedController) panelUpdateClient(c *gin.Context) {
	email, ok := clientEmailParam(c)
	if !ok {
		return
	}
	record, ok := a.ownedRecord(c, email)
	if !ok || !a.permittedClient(c, record) {
		return
	}
	var body struct {
		Enable  *bool   `json:"enable,omitempty"`
		TotalGB *int64  `json:"totalGB,omitempty"`
		Comment *string `json:"comment,omitempty"`
	}
	if err := c.ShouldBindJSON(&body); err != nil ||
		(body.TotalGB != nil && (*body.TotalGB < 0 || *body.TotalGB > maxDelegatedClientQuota)) ||
		(body.Comment != nil && len(*body.Comment) > 100) {
		pureJsonMsg(c, http.StatusBadRequest, false, "Invalid client name or quota.")
		return
	}
	payload, err := json.Marshal(body)
	if err != nil {
		jsonObj(c, nil, err)
		return
	}
	restart, err := a.clients.UpdateByEmailJSON(&a.inbounds, record.Email, payload)
	if restart {
		a.xray.SetToNeedRestart()
	}
	if err == nil {
		if body.Comment != nil && *body.Comment != "" {
			database.GetDB().Model(&model.DelegatedClient{}).
				Where("admin_id = ? AND client_id = ?", panelDelegate(c).ID, record.Id).
				UpdateColumn("label", *body.Comment)
		}
		notifyClientsChanged()
	}
	jsonObj(c, nil, err)
}
