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

# Stdlib
import copy
import os
from shutil import copyfile
from string import Template
# External packages
import yaml
# SCION
from lib.app.sciond import get_default_sciond_path
from lib.defines import SCIOND_API_SOCKDIR
from lib.packet.scion_addr import ISD_AS
from lib.util import (
    read_file,
    write_file,
)
from topology.common import remote_nets

DOCKER_UTIL_CONF = 'utils-dc.yml'
DOCKER_TESTER_CONF = 'testers-dc.yml'


class UtilsGenerator(object):
    def __init__(self, out_dir, topo_dicts, sig, volumes, elem_networks, bridges):
        self.out_dir = out_dir
        self.topo_dicts = topo_dicts
        self.dc_util_conf = {'version': '3', 'services': {}}
        self.dc_tester_conf = {'version': '3', 'services': {}}
        self.elem_networks = elem_networks
        self.sig = sig
        self.volumes = volumes
        self.bridges = bridges
        self.output_base = os.environ.get('SCION_OUTPUT_BASE', os.getcwd())

    def generate(self):
        for topo_id in self.topo_dicts:
            self._create_util_containers()
            self._test_conf(topo_id)
            if self.sig:
                self._sig_test_conf(topo_id)
        self._write_files()
        
        text = ''
        for topo_id in self.topo_dicts:
            ip = self.elem_networks[topo_id.file_fmt()][0]['ipv4']+4
            text += str(topo_id) + ' ' + str(ip) + '\n'
            conf_path = os.path.join(self.out_dir, 'sig-test.conf')
            write_file(conf_path, text)

    def _write_files(self):
        write_file(os.path.join(self.out_dir, DOCKER_UTIL_CONF),
                   yaml.dump(self.dc_util_conf, default_flow_style=False))
        write_file(os.path.join(self.out_dir, DOCKER_TESTER_CONF),
                   yaml.dump(self.dc_tester_conf, default_flow_style=False))

    def _create_util_containers(self):
        entry_chown = {
            'image': 'busybox',
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro'
            ],
            'command': 'chown -R "$LOGNAME:" /run/shm/volumes/.'
        }
        entry_clean = {
            'image': 'busybox',
            'volumes': [],
            'command': 'sh -c "find /run/shm/volumes -type s -print0 | xargs -r0 rm -v"'
        }
        for volume in self.volumes:
            entry_chown['volumes'].append('%s:/run/shm/volumes/%s' % (volume, volume))
            entry_clean['volumes'].append('%s:/run/shm/volumes/%s' % (volume, volume))
        self.dc_util_conf['services']['chowner'] = entry_chown
        self.dc_util_conf['services']['cleaner'] = entry_clean

    def _test_conf(self, topo_id):
        entry = {
            'image': 'scion',
            'environment': {
                'SCION_UID': '$(id -u)',
                'SCION_GID': '$(id -g)',
                'DOCKER_GID': '$(getent group docker | cut -f3 -d:)',
            },
            'volumes': [
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                self.output_base + '/logs:/home/scion/go/src/github.com/scionproto/scion/logs:rw',
                self.output_base + '/gen:/home/scion/go/src/github.com/scionproto/scion/gen:ro'
            ],
            'entrypoint': [
                'sudo /docker-entrypoint.sh'
            ],
            'command': [
                'tail',
                '-f',
                '/dev/null'
            ]
        }
        name = 'tester_%s' % topo_id.file_fmt()
        entry['container_name'] = name
        self.dc_tester_conf['services'][name] = entry

    def _sig_test_conf(self, topo_id):
        net = self.elem_networks[topo_id.file_fmt()][0]
        entry = {
            'image': 'scion_sig_tester',
            'privileged': True,
            'volumes': [
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                self.output_base + '/logs:/home/scion/go/src/github.com/scionproto/scion/logs:rw'
            ],
            'networks': {},
            'entrypoint': [
                './tester.sh',
                str(net['ipv4']+3),
                remote_nets(self.elem_networks, topo_id)
            ],
        }
        name = 'sig_tester_%s' % topo_id.file_fmt()
        entry['container_name'] = name
        entry['networks'][self.bridges[net['net']]] = {'ipv4_address': str(net['ipv4']+4)}
        self.dc_tester_conf['services'][name] = entry
