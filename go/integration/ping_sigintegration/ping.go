// Copyright 2018 ETH Zurich
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

package main

import (
	// "github.com/scionproto/scion/go/lib/common"
	// "io/ioutil"
	"fmt"
	"os"

	"github.com/scionproto/scion/go/lib/integration"
	"github.com/scionproto/scion/go/lib/log"
)

var (
	name = "ping"
)

func main() {
	os.Exit(realMain())
}

func realMain() int {
	if !*integration.Docker {
		fmt.Fprintf(os.Stderr, "Can only run %s\n test with docker.", name)
		return 1
	}
	if err := integration.Init(name); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to init: %s\n", err)
		return 1
	}
	defer log.LogPanicAndExit()
	defer log.Flush()
	
	clientArgs := []string{"sig_tester", integration.SrcIAReplace, "ping", }

	in := integration.NewBinaryIntegration(name, integration.DockerCmd, clientArgs, []string{})
	if err := integration.RunUnaryTests(in, integration.IAPairs()); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to run tests: %s\n", err)
		return 1
	}
	return 0
}

func readTesterCfg() {
	// buffer, err := ioutil.ReadFile("gen/sig-testing.conf")
	// if err != nil {
	// 	return nil, common.NewBasicError("Unable to read from file", err, "name", fileName)
	// }
}
