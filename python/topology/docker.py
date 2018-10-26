# Copyright 2018 ETH Zurich, Anapaya Systems
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
from topology.common import _prom_addr_br, _prom_addr_infra, remote_nets, _sciond_name
from topology.utils import UtilsGenerator

DOCKER_BASE_CONF = 'base-dc.yml'
DOCKER_SCION_CONF = 'scion-dc.yml'
DOCKER_SIG_CONF = 'sig-dc.yml'
DOCKER_NETWORK_CONF = 'dc-networks.conf'

DEFAULT_DOCKER_NETWORK = "172.18.0.0/24"


class DockerGenerator(object):
    def __init__(self, out_dir, topo_dicts, networks, sig, sd, ps):
        self.out_dir = out_dir
        self.topo_dicts = topo_dicts
        self.networks = networks
        self.sig = sig
        self.sd = sd
        self.ps = ps
        self.dc_base_conf = {'version': '3', 'networks': {}, 'volumes': {}}
        self.dc_conf = {'version': '3', 'services': {}}
        self.sig_conf = {'version': '3', 'services': {}}
        self.output_base = os.environ.get('SCION_OUTPUT_BASE', os.getcwd())
        self.user_spec = os.environ.get('SCION_USERSPEC', '$LOGNAME')

        self.elem_networks = {}
        self.bridges = {}

    def generate(self):
        self._base_conf()
        self._zookeeper_conf()
        self._create_networks()
        for topo_id, topo in self.topo_dicts.items():
            base = os.path.join(self.output_base, topo_id.base_dir(self.out_dir))
            self._gen_topo(topo_id, topo, base)
        self._write_files()
        utils_gen = UtilsGenerator(self.out_dir, self.topo_dicts, self.sig,
                                   self.dc_base_conf['volumes'], self.elem_networks, self.bridges)
        utils_gen.generate()

    def _write_files(self):
        write_file(os.path.join(self.out_dir, DOCKER_SCION_CONF),
                   yaml.dump(self.dc_conf, default_flow_style=False))
        write_file(os.path.join(self.out_dir, DOCKER_BASE_CONF),
                   yaml.dump(self.dc_base_conf, default_flow_style=False))
        write_file(os.path.join(self.out_dir, DOCKER_SIG_CONF),
                   yaml.dump(self.sig_conf, default_flow_style=False))

        # Write bridge config file
        text = ''
        for br in self.bridges:
            text += br + ' ' + self.bridges[br] + '\n'
        conf_path = os.path.join(self.out_dir, DOCKER_NETWORK_CONF)
        write_file(conf_path, text)

    def _base_conf(self):
        default_net = {'ipam': {'config': [{'subnet': DEFAULT_DOCKER_NETWORK}]}}
        self.dc_base_conf['networks']['default'] = default_net

    def _gen_topo(self, topo_id, topo, base):
        self._br_conf(topo, base)
        self._cs_conf(topo_id, topo, base)
        self._bs_conf(topo_id, topo, base)
        self._ps_conf(topo_id, topo, base)
        self._dispatcher_conf(topo_id, base)
        self._sciond_conf(topo_id, base)
        self._create_volumes(topo_id)
        if self.sig:
            self._sig_conf(topo_id, topo, base)

    def _create_networks(self):
        for network in self.networks:
            for elem in self.networks[network]:
                if elem not in self.elem_networks:
                    self.elem_networks[elem] = []
                self.elem_networks[elem].append(
                    {'net': str(network), 'ipv4': self.networks[network][elem].ip})
            # Create docker networks/bridges
            net_name = "scn_%03d" % len(self.bridges)
            self.bridges[str(network)] = net_name
            self.dc_base_conf['networks'][net_name] = {'external': True}

    def _create_volumes(self, topo_id):
        self.dc_base_conf['volumes']['vol_disp_%s' % topo_id.file_fmt()] = None
        self.dc_base_conf['volumes']['vol_sciond_%s' % topo_id.file_fmt()] = None

    def _br_conf(self, topo_id, topo, base):
        raw_entry = {
            'image': 'scion_border',
            'networks': {},
            'depends_on': [
                'disp_' + topo_id.file_fmt(),
            ],
            'environment': {
                'SU_EXEC_USERSPEC': self.user_spec,
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                self.output_base + '/logs:/share/logs:rw'
            ],
            'command': []
        }
        for k, v in topo.get("BorderRouters", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            entry['volumes'].append('%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('-id=%s' % k)
            entry['command'].append('-prom=%s' % _prom_addr_br(v))
            for net in self.elem_networks[k]:
                ip = str(net['ipv4'])
                entry['networks'][self.bridges[net['net']]] = {'ipv4_address': ip}
            self.dc_conf['services'][k] = entry

    def _sig_conf(self, topo_id, topo, base):
        name = 'sig_%s' % topo_id.file_fmt()
        net = self.elem_networks[topo_id.file_fmt()][0]
        entry = {
            'image': 'scion_sig_acceptance:latest',
            'container_name': name,
            'cap_add': [
                'NET_ADMIN',
            ],
            'privileged': True,
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '/dev/net/tun:/dev/net/tun',
                '%s/sig:/share/conf' % base,
                self.output_base + '/logs:/share/logs:rw'
            ],
            'networks': {},
            'command': [
                remote_nets(self.elem_networks, topo_id),
                '-id=%s' % name,
                '-ia=%s' % ISD_AS(topo_id.file_fmt()),
                '-ip=%s' % str(net['ipv4']),
                '-config=conf/cfg.json',
            ]
        }
        entry['networks'][self.bridges[net['net']]] = {'ipv4_address': str(net['ipv4']+3)}
        self.sig_conf['services'][name] = entry

    def _cs_conf(self, topo_id, topo, base):
        raw_entry = {
            'image': 'scion_cert_py',
            'depends_on': [
                _sciond_name(topo_id),
                'disp_' + topo_id.file_fmt(),
                'zookeeper'
            ],
            'environment': {
                'SU_EXEC_USERSPEC': self.user_spec,
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                self.output_base + '/gen-cache:/share/cache:rw',
                self.output_base + '/logs:/share/logs:rw'
            ],
            'command': [
                '--spki_cache_dir=cache'
            ]
        }
        for k, v in topo.get("CertificateService", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            entry['volumes'].append('%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('--prom=%s' % _prom_addr_infra(v))
            entry['command'].append(k)
            entry['command'].append('conf')
            self.dc_conf['services'][k] = entry

    def _bs_conf(self, topo_id, topo, base):
        raw_entry = {
            'image': 'scion_beacon_py',
            'depends_on': [
                _sciond_name(topo_id),
                'disp_' + topo_id.file_fmt(),
                'zookeeper'
            ],
            'environment': {
                'SU_EXEC_USERSPEC': self.user_spec,
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                self.output_base + '/gen-cache:/share/cache:rw',
                self.output_base + '/logs:/share/logs:rw'
            ],
            'command': [
                '--spki_cache_dir=cache'
            ]
        }
        for k, v in topo.get("BeaconService", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            entry['volumes'].append('%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('--prom=%s' % _prom_addr_infra(v))
            entry['command'].append(k)
            entry['command'].append('conf')
            self.dc_conf['services'][k] = entry

    def _ps_conf(self, topo_id, topo, base):
        image = 'scion_path_py' if self.ps == 'py' else 'scion_path'
        raw_entry = {
            'image': image,
            'depends_on': [
                _sciond_name(topo_id),
                'disp_' + topo_id.file_fmt(),
                'zookeeper'
            ],
            'environment': {
                'SU_EXEC_USERSPEC': self.user_spec,
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                self.output_base + '/gen-cache:/share/cache:rw',
                self.output_base + '/logs:/share/logs:rw'
            ],
            'command': [],
        }
        for k, v in topo.get("PathService", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            entry['volumes'].append('%s:/share/conf:ro' % os.path.join(base, k))
            if self.ps == 'py':
                entry['command'].append('--spki_cache_dir=cache')
                entry['command'].append('--prom=%s' % _prom_addr_infra(v))
                entry['command'].append(k)
                entry['command'].append('conf')
            self.dc_conf['services'][k] = entry

    def _zookeeper_conf(self):
        cfg_file = 'docker/zoo-container.cfg'
        entry = {
            'image': 'zookeeper:latest',
            'container_name': 'zookeeper',
            'environment': {
                'ZOO_USER': self.user_spec,
                'ZOO_DATA_DIR': '/var/lib/zookeeper',
                'ZOO_DATA_LOG_DIR': '/dev/shm/zookeeper'
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                os.path.join(self.output_base, self.out_dir, cfg_file) + ':/conf/zoo.cfg:rw',
                '/var/lib/docker-zk:/var/lib/zookeeper:rw',
                '/run/shm/docker-zk:/dev/shm/zookeeper:rw'
            ],
            'ports': [
                '2181:2181'
            ]
        }
        self.dc_conf['services']['zookeeper'] = entry
        cfg_path = os.path.join(self.out_dir, cfg_file)
        os.makedirs(os.path.dirname(cfg_path))
        copyfile(os.path.join(os.environ['PWD'], cfg_file), cfg_path)

    def _sciond_conf(self, topo_id, base):
        name = _sciond_name(topo_id)
        image = 'scion_sciond_py' if self.sd == 'py' else 'scion_sciond'
        entry = {
            'image': image,
            'container_name': name,
            'depends_on': [
                'disp_' + topo_id.file_fmt(),
            ],
            'environment': {
                'SU_EXEC_USERSPEC': self.user_spec,
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '%s:/share/conf:ro' % os.path.join(base, 'endhost'),
                self.output_base + '/gen-cache:/share/cache:rw',
                self.output_base + '/logs:/share/logs:rw'
            ],
        }
        if self.sd == 'py':
            entry['command'] = [
                    '--api-addr=%s' % os.path.join(SCIOND_API_SOCKDIR, "%s.sock" % name),
                    '--log_dir=logs',
                    '--spki_cache_dir=cache',
                    name,
                    'conf'
            ]
        self.dc_conf['services'][name] = entry

    def _dispatcher_conf(self, topo_id, base):
        name = 'disp_%s' % topo_id.file_fmt()
        raw_entry = {
            'image': 'scion_dispatcher',
            'container_name': name,
            'environment': {
                'SU_EXEC_USERSPEC': self.user_spec,
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                self.output_base + '/logs:/share/logs:rw'
            ],
            'networks': {},
        }

        # Create dispatcher config
        tmpl = Template(read_file("topology/zlog.tmpl"))
        entry = copy.deepcopy(raw_entry)
        for net in self.elem_networks[topo_id.file_fmt()]:
            entry['networks'][self.bridges[net['net']]] = {'ipv4_address': str(net['ipv4'])}
            entry['volumes'].append('%s:/share/conf:rw' % os.path.join(base, 'dispatcher'))
            self.dc_conf['services'][name] = entry
            cfg = "%s/dispatcher/dispatcher.zlog.conf" % base
            write_file(cfg, tmpl.substitute(name="dispatcher", elem=name))
