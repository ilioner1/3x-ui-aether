package aether

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
)

type Config struct {
	Peer string
	Scan string
	IP string
	Transport string
	Noize string
}

type Desired struct {
	ID string
	Tag string
	Port int
	Config Config
}

func ParseURI(raw string) (Config, error) {
	c := Config{Scan: "balanced", IP: "v4", Transport: "h3", Noize: "firewall"}
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || u == nil || u.Scheme != "aether" || u.User != nil || u.Path != "" || u.Opaque != "" {
		return c, fmt.Errorf("aether: expected aether://IP:port?protocol=masque")
	}
	peer, err := netip.ParseAddrPort(u.Host)
	if err != nil || peer.Port() == 0 || peer.Addr().Zone() != "" || !peer.Addr().IsGlobalUnicast() || peer.Addr().IsPrivate() {
		return c, fmt.Errorf("aether: endpoint must be a public IP and port")
	}
	c.Peer = peer.String()
	q, err := url.ParseQuery(u.RawQuery)
	if err != nil { return c, fmt.Errorf("aether: invalid query: %w", err) }
	choices := map[string][]string{
		"protocol": {"masque"}, "scan": {"turbo", "balanced", "thorough", "stealth", "ironclad"},
		"ip": {"v4", "v6", "both"}, "transport": {"h2", "h3"},
		"noize": {"off", "light", "firewall", "balanced", "gfw", "aggressive"},
	}
	for key, values := range q {
		allowed, exists := choices[key]
		valid := false
		if exists && len(values) == 1 { for _, value := range allowed { valid = valid || values[0] == value } }
		if !valid { return c, fmt.Errorf("aether: unsupported or repeated %q option", key) }
	}
	if q.Has("scan") { c.Scan = q.Get("scan") }
	if q.Has("ip") { c.IP = q.Get("ip") }
	if q.Has("transport") { c.Transport = q.Get("transport") }
	if q.Has("noize") { c.Noize = q.Get("noize") }
	return c, nil
}

func (c Config) Args() []string {
	return []string{"--masque", "--peer", c.Peer, "--scan", c.Scan, "--ip", c.IP, "--"+c.Transport, "--noize", c.Noize, "--no-quick-reconnect"}
}

func IsOutbound(raw []byte) bool {
	var o struct { Protocol string }
	return json.Unmarshal(raw, &o) == nil && strings.EqualFold(o.Protocol, "aether")
}

func ParseOutbound(raw []byte) (string, Config, error) {
	var o struct { Tag string; Settings struct { URI string `json:"uri"` } }
	if err := json.Unmarshal(raw, &o); err != nil { return "", Config{}, fmt.Errorf("aether: invalid outbound: %w", err) }
	if strings.TrimSpace(o.Tag) == "" { return "", Config{}, fmt.Errorf("aether: outbound tag is required") }
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil { return "", Config{}, err }
	for key, value := range fields {
		if key != "protocol" && key != "tag" && key != "settings" && string(value) != "null" {
			return "", Config{}, fmt.Errorf("aether: unsupported outbound field %q", key)
		}
	}
	c, err := ParseURI(o.Settings.URI)
	return o.Tag, c, err
}

// Transform only renders config; it never starts a tunnel while previewing or validating.
func Transform(raw []byte, namespace string) ([]byte, []Desired, error) {
	if len(raw) == 0 { return raw, nil, nil }
	var entries []json.RawMessage
	if err := json.Unmarshal(raw, &entries); err != nil { return nil, nil, err }
	var desired []Desired
	ports := map[int]string{}
	tags := map[string]bool{}
	for i, entry := range entries {
		if !IsOutbound(entry) { continue }
		tag, c, err := ParseOutbound(entry)
		if err != nil { return nil, nil, err }
		if tags[tag] { return nil, nil, fmt.Errorf("aether: duplicate tag %q", tag) }
		tags[tag] = true
		fingerprint, _ := json.Marshal(struct { Tag string; Config Config }{tag, c})
		sum := sha256.Sum256(append([]byte(namespace+"\x00"), fingerprint...))
		id := hex.EncodeToString(sum[:])
		port := 20000 + int(binary.BigEndian.Uint32(sum[:4])%40000)
		if other, taken := ports[port]; taken { return nil, nil, fmt.Errorf("aether: bridge port collision for %q and %q; change one tag", other, tag) }
		ports[port] = tag
		desired = append(desired, Desired{ID:id, Tag:tag, Port:port, Config:c})
		entries[i], err = json.Marshal(map[string]any{"tag":tag,"protocol":"socks","settings":map[string]any{"servers":[]any{map[string]any{"address":"127.0.0.1","port":port}}}})
		if err != nil { return nil, nil, err }
	}
	if len(desired) == 0 { return raw, nil, nil }
	data, err := json.Marshal(entries)
	return data, desired, err
}

func (d Desired) Address() string { return "127.0.0.1:"+strconv.Itoa(d.Port) }
