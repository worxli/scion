#!/usr/bin/python3
# Copyright 2018 ETH Zurich
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


def _prom_addr_br(br_ele):
    """Get the prometheus address for a border router"""
    int_addr = br_ele['InternalAddr']['Public'][0]
    return "[%s]:%s" % (int_addr['Addr'].ip, int_addr['L4Port'] + 1)


def _prom_addr_infra(infra_ele):
    """Get the prometheus address for an infrastructure element."""
    int_addr = infra_ele["Public"][0]
    return "[%s]:%s" % (int_addr["Addr"].ip, int_addr["L4Port"] + 1)
