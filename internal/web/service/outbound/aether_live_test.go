package outbound

import (
	"encoding/json"
	"os"
	"testing"
)

func TestAetherLiveTunnel(t *testing.T) {
	if os.Getenv("XUI_AETHER_E2E") != "1" { t.Skip("set XUI_AETHER_E2E=1 to contact the real MASQUE gateway") }
	const outbound = `{"protocol":"aether","tag":"mokhaberaat2","settings":{"uri":"aether://162.159.198.223:443?protocol=masque&scan=balanced&ip=v4&transport=h2#mokhaberaat2"}}`
	result, err := (&OutboundService{}).TestOutbound(outbound,"https://www.cloudflare.com/cdn-cgi/trace","","real")
	if err != nil { t.Fatal(err) }
	data, err := json.MarshalIndent(result,"","  ")
	if err != nil { t.Fatal(err) }
	t.Logf("real Aether + Xray tunnel probe: %s", data)
	if path := os.Getenv("XUI_AETHER_RESULT"); path != "" {
		if err := os.WriteFile(path,data,0o600); err != nil { t.Fatal(err) }
	}
	if !result.Success || result.HTTPStatus != 200 || result.Delay <= 0 { t.Fatalf("tunnel failed: %s", data) }
}
