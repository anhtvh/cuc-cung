check:
	go vet ./...
	golint ./...

generate:
	go generate ./...

test: generate
	go test ./... -cover -race

test-integration: generate
	go test ./... -cover -race -tags=integration -count=1

build: generate
	GOOS=linux CGO_ENABLED=0 go build -o ${BIN_NAME} ./main.go

clean:
	rm ${BIN_NAME}

sync: build
	rsync -aurv ${BIN_NAME} entry-point.sh config ${SB_SSH_HOST}:${SB_APP_DIR}

restart:
	ssh ${SB_SSH_HOST} docker restart ${SB_DOCKER_NAME}

sandbox: test sync restart

# run the application locally,
# make sure that you already call make dev-up (if not, do it and wait about 2-3s)
run: 						## Run the application locally, make sure that you already call make dev-up (if not, do it and wait about 2-3s)
	 CONFIG_PATH=config/local.yaml go run main.go

cover:
	go test -v -coverpkg=./... $$(go list ./... | grep -v /test ) -coverprofile=coverage.out -covermode=count -json
	go tool cover -func coverage.out

# dev-up setup environment for running the application locally
# (except for external APIs)
dev-up:
	cd ./devstack && docker-compose up -d

# dev-down shutdown the environment
dev-down:
	cd ./devstack && docker-compose down

# log-sb use vscode to open log file, then stream log from sandbox to that file
# example: make log-sb tail=200
log-sb:
	code log/system.log
	ssh ${SB_SSH_HOST} docker logs -f --tail=$(tail) ${SB_DOCKER_NAME} &> log/system.log