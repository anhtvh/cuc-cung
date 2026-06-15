//go:generate mockgen -source=cache.go -package=mocks -destination=./mocks/cache.go

package caching

import (
	"context"
	"time"

	"github.com/go-redis/redis/v8"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/logging"
)

type Service interface {
	SetNXTransID(ctx context.Context, funcName string, transID string, expireDate time.Duration) bool
}

type cacheService struct {
	cache *redis.Client
	cfg   CacheConfig
}

// CacheConfig is the required config for constructing cacheService
type CacheConfig struct {
	CachePrefix string `json:"cachePrefix"`
}

func NewCacheService(cfg CacheConfig, redisCli *redis.Client) Service {
	return &cacheService{
		cache: redisCli,
		cfg:   cfg,
	}
}

func (c *cacheService) SetNXTransID(ctx context.Context, funcName string, transID string, expireDate time.Duration) bool {
	result, err := c.cache.SetNX(ctx, c.getCheckTransIDKey(funcName, transID), transID, expireDate).Result()
	if err != nil {
		logging.FromContext(ctx).Warnf("set nx trans_id err: %v", err.Error())
		return false
	}
	return result
}
