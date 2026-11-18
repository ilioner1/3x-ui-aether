//go:build !windows

package aether

import (
	"context"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAetherProcessHelper(t *testing.T) {
	if os.Getenv("XUI_AETHER_HELPER") != "1" {
		return
	}
	listener, err := net.Listen("tcp", os.Getenv("AETHER_SOCKS"))
	if err != nil {
		os.Exit(2)
	}
	for {
		conn, err := listener.Accept()
		if err != nil {
			os.Exit(3)
		}
		go func() {
			defer conn.Close()
			var hello [3]byte
			if _, err := io.ReadFull(conn, hello[:]); err == nil && os.Getenv("XUI_AETHER_HELPER_STALL") != "1" {
				_, _ = conn.Write([]byte{5, 0})
			}
		}()
	}
}

func TestFailedReplacementKeepsOldTunnelAndStopsNewChildren(t *testing.T) {
	t.Setenv("XUI_AETHER_HELPER", "1")
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	launcher := filepath.Join(t.TempDir(), "aether")
	script := "#!/bin/sh\nexec '" + strings.ReplaceAll(executable, "'", "'\"'\"'") + "' -test.run=TestAetherProcessHelper -- \"$@\"\n"
	if err := os.WriteFile(launcher, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	manager := NewManager(t.TempDir(), launcher)
	t.Cleanup(manager.StopAll)
	makeDesired := func(id string) Desired {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		port := l.Addr().(*net.TCPAddr).Port
		_ = l.Close()
		c, err := ParseURI(sampleURI)
		if err != nil {
			t.Fatal(err)
		}
		return Desired{ID: id, Tag: id, Port: port, Config: c}
	}
	old, next, busy := makeDesired("old"), makeDesired("next"), makeDesired("busy")
	occupied, err := net.Listen("tcp", busy.Address())
	if err != nil {
		t.Fatal(err)
	}
	defer occupied.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if err := manager.Ensure(ctx, []Desired{old}); err != nil {
		t.Fatal(err)
	}
	if err := manager.Ensure(ctx, []Desired{next, busy}); err == nil || !strings.Contains(err.Error(), "unavailable") {
		t.Fatalf("wrong collision result: %v", err)
	}
	if !socksReady(old.Address()) {
		t.Fatal("failed replacement killed the old tunnel")
	}
	crashed := manager.children[old.ID]
	if err := crashed.cmd.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	<-crashed.done
	if err := manager.Ensure(ctx, []Desired{old}); err != nil {
		t.Fatalf("could not restart crashed child: %v", err)
	}
	if !socksReady(old.Address()) {
		t.Fatal("restarted child did not serve SOCKS")
	}
	for _, address := range []string{next.Address()} {
		l, err := net.Listen("tcp", address)
		if err != nil {
			t.Fatalf("failed replacement leaked a child on %s: %v", address, err)
		}
		_ = l.Close()
	}
	manager.StopAll()
	l, err := net.Listen("tcp", old.Address())
	if err != nil {
		t.Fatalf("StopAll left tunnel running: %v", err)
	}
	_ = l.Close()
}

func TestLiveListenersStartWithoutRemoteSOCKSReadiness(t *testing.T) {
	t.Setenv("XUI_AETHER_HELPER", "1")
	t.Setenv("XUI_AETHER_HELPER_STALL", "1")
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	launcher := filepath.Join(t.TempDir(), "aether")
	script := "#!/bin/sh\nexec '" + strings.ReplaceAll(executable, "'", "'\"'\"'") + "' -test.run=TestAetherProcessHelper -- \"$@\"\n"
	if err := os.WriteFile(launcher, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	manager := NewManager(t.TempDir(), launcher)
	t.Cleanup(manager.StopAll)
	var desired []Desired
	var reservations []net.Listener
	for i := range 6 {
		reservation, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		reservations = append(reservations, reservation)
		tag := fmt.Sprintf("aether-%d", i+1)
		desired = append(desired, Desired{ID: tag, Tag: tag, Port: reservation.Addr().(*net.TCPAddr).Port})
	}
	for _, reservation := range reservations {
		_ = reservation.Close()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := manager.EnsureListeners(ctx, desired); err != nil {
		t.Fatal(err)
	}
	for _, d := range desired {
		if !tcpListenerReady(d.Address()) || socksReady(d.Address()) {
			t.Fatalf("bridge %q should be bound with SOCKS still pending", d.Tag)
		}
	}
}
