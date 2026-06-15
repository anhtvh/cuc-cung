package caching

import "fmt"

func (c *cacheService) getCheckTransIDKey(funcName, transID string) string {
	return fmt.Sprintf("%s|%s|check_dupplicated_trans_id|%s", c.cfg.CachePrefix, funcName, transID)
}
