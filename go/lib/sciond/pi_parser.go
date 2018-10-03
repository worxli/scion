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

package sciond

import (
	"regexp"
	"strconv"

	"github.com/scionproto/scion/go/lib/addr"
	"github.com/scionproto/scion/go/lib/common"
)

var pathInterfaceParserRegex = regexp.MustCompile("(?P<ISD>[0-9]+)(-(?P<AS>[0-9]+))?(#(?P<IFID>[0-9]+))?")

func parsePathInterface(str string) (*parseResult, error) {
	submatches := pathInterfaceParserRegex.FindStringSubmatch(str)
	if !isExactMatch(submatches, str) {
		return nil, common.NewBasicError("Failed to parse interface spec", nil, "value", str)
	}
	captureMap := getCaptureMap(submatches)
	return &parseResult{
		isd:  captureMap["ISD"],
		as:   captureMap["AS"],
		ifid: captureMap["IFID"],
	}, nil
}

func getCaptureMap(submatches []string) map[string]string {
	captureMap := make(map[string]string)
	for i, name := range pathInterfaceParserRegex.SubexpNames() {
		if i != 0 && name != "" {
			captureMap[name] = submatches[i]
		}
	}
	return captureMap
}

func isExactMatch(submatches []string, str string) bool {
	if len(submatches) > 0 && len(submatches[0]) == len(str) {
		return true
	}
	return false
}

type parseResult struct {
	isd  string
	as   string
	ifid string
}

func (result *parseResult) ToPathInterface() (PathInterface, error) {
	isd, err := addr.ISDFromString(result.isd)
	if err != nil {
		return PathInterface{}, err
	}
	as, err := parseASWithDefault(result.as)
	if err != nil {
		return PathInterface{}, err
	}
	ifid, err := parseIFIDWithDefault(result.ifid)
	if err != nil {
		return PathInterface{}, err
	}
	return PathInterface{RawIsdas: addr.IA{I: isd, A: as}.IAInt(), IfID: ifid}, nil
}

func parseASWithDefault(str string) (addr.AS, error) {
	if str == "" {
		return 0, nil
	}
	as, err := addr.ASFromString(str)
	if err != nil {
		return 0, err
	}
	return as, nil
}

func parseIFIDWithDefault(str string) (common.IFIDType, error) {
	if str == "" {
		return 0, nil
	}
	ifid, err := strconv.Atoi(str)
	return common.IFIDType(ifid), err
}

func isValidPredicate(iface PathInterface) bool {
	if iface.ISD_AS().I == 0 && iface.ISD_AS().A == 0 && iface.IfID != 0 {
		return false
	}
	if iface.ISD_AS().I != 0 && iface.ISD_AS().A == 0 && iface.IfID != 0 {
		return false
	}
	return true
}
