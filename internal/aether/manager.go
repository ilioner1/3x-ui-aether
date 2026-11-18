package aether

import (
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type child struct {
	cmd  *exec.Cmd
	done chan struct{}
}
type Manager struct {
	mu       sync.Mutex
	root     string
	binary   string
	children map[string]*child
	desired  []Desired
}

func NewManager(root, binary string) *Manager {
	return &Manager{root: root, binary: binary, children: map[string]*child{}}
}

// Ensure waits for SOCKS readiness when the caller needs to probe the actual tunnel.
func (m *Manager) Ensure(ctx context.Context, desired []Desired) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.ensureLocked(ctx, desired, socksReady, false)
}

// EnsureListeners waits only for the listener Aether holds during connection.
// Live Xray routes can then use it while the remote tunnel is still connecting.
func (m *Manager) EnsureListeners(ctx context.Context, desired []Desired) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.ensureLocked(ctx, desired, tcpListenerReady, false)
}

func (m *Manager) ensureLocked(ctx context.Context, desired []Desired, ready func(string) bool, keepSuccessful bool) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	started := make([]*child, len(desired))
	var workers sync.WaitGroup
	var firstErr error
	var recordError sync.Once

	for i, d := range desired {
		if cur := m.children[d.ID]; cur != nil {
			select {
			case <-cur.done:
				delete(m.children, d.ID)
			default:
				continue
			}
		}
		workers.Go(func() {
			cur, err := m.start(ctx, d, ready)
			if err != nil {
				recordError.Do(func() {
					firstErr = fmt.Errorf("aether outbound %q: %w", d.Tag, err)
					if !keepSuccessful {
						cancel()
					}
				})
				return
			}
			started[i] = cur
		})
	}
	workers.Wait()

	var cleanup sync.WaitGroup
	for i, cur := range started {
		if cur == nil {
			continue
		}
		if firstErr != nil && !keepSuccessful {
			cleanup.Go(func() { stop(cur) })
		} else {
			m.children[desired[i].ID] = cur
		}
	}
	cleanup.Wait()
	return firstErr
}

func (m *Manager) start(ctx context.Context, d Desired, ready func(string) bool) (*child, error) {
	listener, err := (&net.ListenConfig{}).Listen(ctx, "tcp", d.Address())
	if err != nil {
		return nil, fmt.Errorf("bridge address %s unavailable: %w", d.Address(), err)
	}
	_ = listener.Close()
	dir := filepath.Join(m.root, d.ID)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	logFile, err := os.OpenFile(filepath.Join(dir, "core.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return nil, err
	}
	args := append(d.Config.Args(), "--config", filepath.Join(dir, "identity.toml"))
	bind := d.Address()
	if d.Config.Psiphon {
		// Xray must dial Psiphon, while Psiphon dials the base Aether tunnel.
		bind = "127.0.0.1:0"
		args = append(args, "--psiphon", "--psiphon-bind", d.Address(), "--psiphon-mode", d.Config.PsiphonMode)
		if d.Config.Region != "" {
			args = append(args, "--psiphon-region", d.Config.Region)
		}
	}
	cmd := exec.CommandContext(context.Background(), m.binary, args...)
	cmd.Dir = dir
	for _, value := range os.Environ() {
		if !strings.HasPrefix(strings.ToUpper(value), "AETHER_") {
			cmd.Env = append(cmd.Env, value)
		}
	}
	cmd.Env = append(cmd.Env, "AETHER_SOCKS="+bind)
	cmd.Stdout, cmd.Stderr = logFile, logFile
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		return nil, err
	}
	cur := &child{cmd: cmd, done: make(chan struct{})}
	go func() { _ = cmd.Wait(); _ = logFile.Close(); close(cur.done) }()
	ticker := time.NewTicker(150 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			stop(cur)
			return nil, fmt.Errorf("startup timed out; inspect %s: %w", filepath.Join(dir, "core.log"), ctx.Err())
		case <-cur.done:
			return nil, fmt.Errorf("core exited before SOCKS readiness; inspect %s", filepath.Join(dir, "core.log"))
		case <-ticker.C:
			if ready(d.Address()) {
				select {
				case <-cur.done:
					return nil, fmt.Errorf("core exited before bridge readiness; inspect %s", filepath.Join(dir, "core.log"))
				default:
					return cur, nil
				}
			}
		}
	}
}

func tcpListenerReady(address string) bool {
	conn, err := net.DialTimeout("tcp", address, 100*time.Millisecond)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func socksReady(address string) bool {
	conn, err := (&net.Dialer{Timeout: 100 * time.Millisecond}).DialContext(context.Background(), "tcp", address)
	if err != nil {
		return false
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(200 * time.Millisecond))
	if _, err := conn.Write([]byte{5, 1, 0}); err != nil {
		return false
	}
	var reply [2]byte
	_, err = io.ReadFull(conn, reply[:])
	return err == nil && reply == [2]byte{5, 0}
}

func stop(c *child) {
	if c == nil {
		return
	}
	select {
	case <-c.done:
		return
	default:
	}
	_ = c.cmd.Process.Signal(os.Interrupt)
	select {
	case <-c.done:
	case <-time.After(3 * time.Second):
		_ = c.cmd.Process.Kill()
		<-c.done
	}
}

func (m *Manager) Retain(desired []Desired) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.desired = append([]Desired(nil), desired...)
	wanted := map[string]bool{}
	for _, d := range desired {
		wanted[d.ID] = true
	}
	var cleanup sync.WaitGroup
	for id, cur := range m.children {
		if !wanted[id] {
			cleanup.Go(func() { stop(cur) })
			delete(m.children, id)
		}
	}
	cleanup.Wait()
}

func (m *Manager) StopAll() { m.Retain(nil) }

func (m *Manager) Watch(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			m.mu.Lock()
			attempt, cancel := context.WithTimeout(ctx, 3*time.Second)
			if err := m.ensureLocked(attempt, m.desired, tcpListenerReady, true); err != nil {
				log.Printf("Aether restart: %v", err)
			}
			cancel()
			m.mu.Unlock()
		}
	}
}
