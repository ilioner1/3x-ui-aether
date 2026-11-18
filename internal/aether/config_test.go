package aether

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

const sampleURI = "aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2"

func TestImportBuildsLoopbackBridgeAndPreservesRoutingTag(t *testing.T) {
	raw := []byte(`[{"protocol":"aether","tag":"mokhaberaat2","settings":{"uri":"` + sampleURI + `"}}]`)
	bridged, desired, err := Transform(raw, "live")
	if err != nil {
		t.Fatal(err)
	}
	var entries []struct {
		Protocol string
		Tag      string
		Settings struct {
			Servers []struct {
				Address string
				Port    int
			}
		}
	}
	if err := json.Unmarshal(bridged, &entries); err != nil {
		t.Fatal(err)
	}
	if len(desired) != 1 || len(entries) != 1 || entries[0].Protocol != "socks" || entries[0].Tag != "mokhaberaat2" || entries[0].Settings.Servers[0].Address != "127.0.0.1" || entries[0].Settings.Servers[0].Port != desired[0].Port {
		t.Fatalf("incorrect bridge: %s / %+v", bridged, desired)
	}
	if got := strings.Join(desired[0].Config.Args(), " "); got != "--masque --peer 162.159.198.223:443 --scan balanced --ip v4 --h2 --noize firewall --no-quick-reconnect" {
		t.Fatalf("wrong CLI: %s", got)
	}
}

func TestRejectsLinkOptionsThatCouldChangeLocalExecution(t *testing.T) {
	for _, query := range []string{"config=/tmp/key", "protocol=invalid", "transport=udp", "scan=balanced&scan=turbo", "ip=garbage", "noize=--help"} {
		_, err := ParseURI("aether://162.159.198.223:443?" + query)
		if err == nil || !strings.Contains(err.Error(), "aether:") {
			t.Fatalf("accepted invalid option %q: %v", query, err)
		}
	}
}

func TestRemarkAndQueryOrderingDoNotRestartAnUnchangedTunnel(t *testing.T) {
	a, err := ParseURI(sampleURI)
	if err != nil {
		t.Fatal(err)
	}
	b, err := ParseURI("aether://162.159.198.223:443?transport=h2&ip=v4&scan=balanced&protocol=masque#renamed")
	if err != nil {
		t.Fatal(err)
	}
	if a != b {
		t.Fatalf("same tunnel has different identity: %+v / %+v", a, b)
	}
}

func TestPsiphonChainURI(t *testing.T) {
	const uri = "aether://162.159.199.111:1701?protocol=masque&scan=thorough&ip=v4&transport=h2&psiphon=chain&psiphon_mode=auto&region=IN#mokhaberaat"
	cfg, err := ParseURI(uri)
	if err != nil || !cfg.Psiphon || cfg.PsiphonMode != "auto" || cfg.Region != "IN" || cfg.Peer != "162.159.199.111:1701" {
		t.Fatalf("ParseURI() = %+v, %v", cfg, err)
	}
	for _, query := range []string{"region=IN", "psiphon_mode=auto", "psiphon=reverse", "psiphon=chain&region=IND", "psiphon=chain&region=IN&region=DE"} {
		if _, err := ParseURI("aether://162.159.199.111:1701?" + query); err == nil {
			t.Errorf("accepted invalid options %q", query)
		}
	}
}

func TestBridgePortCollisionKeepsExistingTunnel(t *testing.T) {
	makeOutbound := func(tag string) string {
		return fmt.Sprintf(`{"protocol":"aether","tag":%q,"settings":{"uri":%q}}`, tag, sampleURI)
	}
	seen := make(map[int]string)
	for i := range 1000 {
		tag := fmt.Sprintf("aether-%d", i)
		entry := makeOutbound(tag)
		_, single, err := Transform([]byte("["+entry+"]"), "live")
		if err != nil {
			t.Fatal(err)
		}
		port := single[0].Port
		first, collision := seen[port]
		if !collision {
			seen[port] = entry
			continue
		}
		_, original, err := Transform([]byte("["+first+"]"), "live")
		if err != nil {
			t.Fatal(err)
		}
		raw := []byte("[" + entry + "," + first + "]")
		_, assigned, err := transform(raw, "live", map[string]int{original[0].ID: port}, nil, nil)
		if err != nil {
			t.Fatal(err)
		}
		if assigned[1].Port != port || assigned[0].Port == port {
			t.Fatalf("new bridge took an active port: %+v", assigned)
		}
		_, distinct, err := Transform(raw, "live")
		if err != nil || distinct[0].Port == distinct[1].Port {
			t.Fatalf("colliding ports were not separated: %+v, %v", distinct, err)
		}
		return
	}
	t.Fatal("test fixture did not produce a port collision")
}

func TestBridgePortAllocationSkipsOccupiedAndReservedPorts(t *testing.T) {
	raw := []byte(`[{"protocol":"aether","tag":"test","settings":{"uri":"` + sampleURI + `"}}]`)
	_, original, err := Transform(raw, "live")
	if err != nil {
		t.Fatal(err)
	}
	port := original[0].Port
	next := firstBridgePort + (port-firstBridgePort+1)%bridgePortCount
	_, assigned, err := transform(raw, "live", nil, map[int]bool{next: true}, func(p int) bool {
		return p != port
	})
	if err != nil {
		t.Fatal(err)
	}
	if assigned[0].Port == port || assigned[0].Port == next {
		t.Fatalf("selected occupied or reserved port: %+v", assigned)
	}
}
