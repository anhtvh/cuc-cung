package config

import (
	"errors"
	"fmt"

	"github.com/spf13/viper"
)

// Load the config from env variables or from the given config file
func Load(path string, cfg interface{}) error {
	if path == "" {
		return errors.New("CONFIG_PATH empty")
	}

	v := viper.New()
	v.SetConfigFile(path)

	if err := v.ReadInConfig(); err != nil {
		return fmt.Errorf("read config err %w", err)
	}

	if err := v.Unmarshal(&cfg); err != nil {
		return fmt.Errorf("unmarshal config err %w", err)
	}

	return nil
}
