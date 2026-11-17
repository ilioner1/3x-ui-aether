package aether

import (
	"encoding/json"
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
