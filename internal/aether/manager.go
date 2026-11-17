package aether

import (
	"context"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"
	"strings"
)

type child struct { cmd *exec.Cmd; done chan struct{}; log *os.File }
type Manager struct { mu sync.Mutex; root string; binary string; children map[string]*child }

func NewManager(root, binary string) *Manager {
	return &Manager{root:root, binary:binary, children:map[string]*child{}}
}

// Ensure starts replacements before Retain removes old tunnels, preserving a working route on failure.
func (m *Manager) Ensure(ctx context.Context, desired []Desired) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	var started []string
	for _, d := range desired {
		if cur := m.children[d.ID]; cur != nil {
			select { case <-cur.done: delete(m.children, d.ID); default: continue }
		}
		cur, err := m.start(ctx, d)
		if err != nil {
			for _, id := range started { stop(m.children[id]); delete(m.children, id) }
			return fmt.Errorf("aether outbound %q: %w", d.Tag, err)
		}
		m.children[d.ID] = cur
		started = append(started, d.ID)
	}
	return nil
}

func (m *Manager) start(ctx context.Context, d Desired) (*child, error) {
	listener, err := net.Listen("tcp", d.Address())
	if err != nil { return nil, fmt.Errorf("bridge address %s unavailable: %w", d.Address(), err) }
	_ = listener.Close()
	dir := filepath.Join(m.root, d.ID)
	if err := os.MkdirAll(dir, 0o700); err != nil { return nil, err }
	logFile, err := os.OpenFile(filepath.Join(dir,"core.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil { return nil, err }
	args := append(d.Config.Args(), "--config", filepath.Join(dir,"identity.toml"))
	cmd := exec.Command(m.binary, args...)
	cmd.Dir = dir
	for _, value := range os.Environ() {
		if !strings.HasPrefix(strings.ToUpper(value),"AETHER_") { cmd.Env = append(cmd.Env,value) }
	}
	cmd.Env = append(cmd.Env,"AETHER_SOCKS="+d.Address())
	cmd.Stdout, cmd.Stderr = logFile, logFile
	if err := cmd.Start(); err != nil { _ = logFile.Close(); return nil, err }
	cur := &child{cmd:cmd, done:make(chan struct{}), log:logFile}
	go func() { _ = cmd.Wait(); _ = logFile.Close(); close(cur.done) }()
	ticker := time.NewTicker(150*time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done(): stop(cur); return nil, fmt.Errorf("startup timed out; inspect %s: %w", filepath.Join(dir,"core.log"), ctx.Err())
		case <-cur.done: return nil, fmt.Errorf("core exited before SOCKS readiness; inspect %s", filepath.Join(dir,"core.log"))
		case <-ticker.C:
			if socksReady(d.Address()) { return cur, nil }
		}
	}
}

func socksReady(address string) bool {
	conn, err := net.DialTimeout("tcp", address, 100*time.Millisecond)
	if err != nil { return false }
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(200*time.Millisecond))
	if _, err := conn.Write([]byte{5,1,0}); err != nil { return false }
	var reply [2]byte
	_, err = io.ReadFull(conn,reply[:])
	return err == nil && reply == [2]byte{5,0}
}

func stop(c *child) {
	if c == nil { return }
	select { case <-c.done: return; default: }
	_ = c.cmd.Process.Signal(os.Interrupt)
	select {
	case <-c.done:
	case <-time.After(3*time.Second):
		_ = c.cmd.Process.Kill()
		<-c.done
	}
}

func (m *Manager) Retain(desired []Desired) {
	m.mu.Lock()
	defer m.mu.Unlock()
	wanted := map[string]bool{}
	for _, d := range desired { wanted[d.ID] = true }
	for id, cur := range m.children { if !wanted[id] { stop(cur); delete(m.children,id) } }
}

func (m *Manager) StopAll() { m.Retain(nil) }
