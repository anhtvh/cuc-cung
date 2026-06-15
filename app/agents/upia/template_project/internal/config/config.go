package config

type Configuration struct {
	App      App
	Proxy    Proxy
	Provider Provider
	Tracing  Tracing
	Cache    Cache
}

type App struct {
	Env       string            `mapstructure:"env"`
	Addr      string            `mapstructure:"addr"`
	ClientMap map[string]string `mapstructure:"client_map"`
}

type Proxy struct {
	Addr string `mapstructure:"addr"`
}
type Account struct {
	UserName string `mapstructure:"username"`
	Password string `mapstructure:"password"`
}
type Provider struct {
	Endpoint      string  `mapstructure:"endpoint"`
	Account1      Account `mapstructure:"account1"`
	Account2      Account `mapstructure:"account2"`
	SkipVerifySSL bool    `mapstructure:"skip_verify_ssl"`
	PrivateKey    string  `mapstructure:"private_key"`
	PublicKey     string  `mapstructure:"public_key"`
	MinAmount     int32   `mapstructure:"min_amount"`
}

type Tracing struct {
	// Agent collects tracing info (jaeger concept)
	Addr string `mapstructure:"addr"`
}

type Cache struct {
	RedisAddr   string `json:"redis_addr" mapstructure:"redis_addr"`
	RedisPass   string `json:"redis_pass" mapstructure:"redis_pass"`
	PoolSize    int    `json:"pool_size" mapstructure:"pool_size"`
	CachePrefix string `json:"cache_prefix" mapstructure:"cache_prefix"`
}
