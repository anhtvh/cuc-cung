package main

import (
	"os"

	"gitlab.zalopay.vn/aqr/bill/provider-imedia/cmd"
	"gitlab.zalopay.vn/aqr/bill/provider-imedia/internal/config"
)

func main() {
	var cfg config.Configuration
	configPath := os.Getenv("CONFIG_PATH")

	err := config.Load(configPath, &cfg)
	if err != nil {
		panic(err)
	}

	srv := cmd.NewServer(cfg)
	srv.InitAndServe()
}
