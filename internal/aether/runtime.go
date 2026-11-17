package aether

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"sync"

	"github.com/mhsanaei/3x-ui/v3/internal/config"
)

func BinaryPath() string {
	if path := os.Getenv("XUI_AETHER_BINARY"); path != "" {
		absolute, _ := filepath.Abs(path)
		return absolute
	}
	name := "aether"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	path, _ := filepath.Abs(filepath.Join(config.GetBinFolderPath(), name))
	return path
}

var (
	liveOnce sync.Once
	live     *Manager
)

func LiveManager() *Manager {
	liveOnce.Do(func() {
		root, _ := filepath.Abs(filepath.Join(config.GetDBFolderPath(), "aether"))
		live = NewManager(root, BinaryPath())
		go live.Watch(context.Background())
	})
	return live
}
