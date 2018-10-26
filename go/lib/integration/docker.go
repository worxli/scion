// Copyright 2018 Anapaya Systems
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package integration

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strings"

	"github.com/scionproto/scion/go/lib/addr"
	"github.com/scionproto/scion/go/lib/log"
)

const (
	dockerCmd = "./tools/dc"
	dockerArg = "run_tester"
)

var _ Integration = (*dockerIntegration)(nil)

var (
	// Container indicates the container name prefix where the test should be executed in
	Container = flag.String("c", "", "Docker container name prefix (e.g. tester_)")
)

type dockerIntegration struct {
	name        string
	cmd         string
	cntrPref    string
	clientArgs  []string
	serverArgs  []string
	logRedirect LogRedirect
}

// NewDockerIntegration returns an implementation of the Integration interface.
// Start will execute the command in a running docker container and use the given arguments for
// the client/server.
// Use SrcIAReplace and DstIAReplace in arguments as placeholder for the source and destination IAs.
// When starting a client/server the placeholders will be replaced with the actual values.
// The server should output the ReadySignal to Stdout once it is ready to accept clients.
func NewDockerIntegration(name, cntrPref, cmd string, clientArgs, serverArgs []string,
	logRedirect LogRedirect) Integration {

	return &dockerIntegration{
		name:        name,
		cmd:         cmd,
		cntrPref:    cntrPref,
		clientArgs:  clientArgs,
		serverArgs:  serverArgs,
		logRedirect: logRedirect,
	}
}

func (bi *dockerIntegration) Name() string {
	return bi.name
}

// StartServer starts a server and blocks until the ReadySignal is received on Stdout.
func (bi *dockerIntegration) StartServer(ctx context.Context, dst addr.IA) (Waiter, error) {
	args := replacePattern(DstIAReplace, dst.String(), bi.serverArgs)
	args = append([]string{dockerArg, bi.cntrPref, dst.FileFmt(false), bi.cmd}, args...)
	r := &binaryWaiter{
		exec.CommandContext(ctx, dockerCmd, args...),
	}
	r.Env = os.Environ()
	r.Env = append(r.Env, fmt.Sprintf("%s=1", GoIntegrationEnv))
	ep, err := r.StderrPipe()
	if err != nil {
		return nil, err
	}
	sp, err := r.StdoutPipe()
	if err != nil {
		return nil, err
	}
	ready := make(chan struct{})
	// parse until we have the ready signal.
	// and then discard the output until the end (required by StdoutPipe).
	go func() {
		defer log.LogPanicAndExit()
		defer sp.Close()
		signal := fmt.Sprintf("%s%s", ReadySignal, dst)
		init := true
		scanner := bufio.NewScanner(sp)
		for scanner.Scan() {
			line := scanner.Text()
			fmt.Println(line)
			if strings.HasPrefix(line, portString) {
				serverPort = strings.TrimPrefix(line, portString)
			}
			if init && signal == line {
				close(ready)
				init = false
			}
		}
	}()
	go bi.logRedirect("Server", "ServerErr", dst, ep)
	err = r.Start()
	if err != nil {
		return nil, err
	}
	select {
	case <-ready:
		return r, err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (bi *dockerIntegration) StartClient(ctx context.Context, src, dst addr.IA) (Waiter, error) {
	args := replacePattern(SrcIAReplace, src.String(), bi.clientArgs)
	args = replacePattern(DstIAReplace, dst.String(), args)
	args = replacePattern(ServerPortReplace, serverPort, args)
	args = append([]string{dockerArg, bi.cntrPref, src.FileFmt(false), bi.cmd}, args...)
	r := &binaryWaiter{
		exec.CommandContext(ctx, dockerCmd, args...),
	}
	r.Env = os.Environ()
	r.Env = append(r.Env, fmt.Sprintf("%s=1", GoIntegrationEnv))
	ep, err := r.StderrPipe()
	sp, err := r.StdoutPipe()
	if err != nil {
		return nil, err
	}
	go bi.logRedirect("Client", "ClientErr", src, ep)
	go bi.logRedirect("Client", "ClientOut", src, sp)
	return r, r.Start()
}
