#!/bin/bash
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

cmd_help() {
	echo
	cat <<-_EOF
	Usage:
	    $PROGRAM scion [docker-compose command]
	        Run docker-compose command for scion services.
	    $PROGRAM utils [docker-compose command]
	        Run docker-compose command for util services.
	    $PROGRAM tester [command]
	        Run a command in the `tester` container.
	    $PROGRAM sig_tester [ia] [command]
	        Run a command in the `tester` container.
	_EOF
}

cmd_init() {
	FILE="gen/dc-networks.conf"
	while read line; do
		vars=( $line )
		local name="${vars[1]}"
		docker network inspect "$name" &> /dev/null
		if [[ $? -eq 0 ]]; then
			echo "Network $name already exists, skip creating."
		else
			echo "Creating network $name: $(docker network create --driver=bridge --subnet="${vars[0]}" -o "com.docker.network.bridge.name=$name" "$name")"
		fi
	done < $FILE
	cmd_utils up -d chowner
}

cmd_scion() {
	COMPOSE_FILE="gen/base-dc.yml:gen/scion-dc.yml" docker-compose "$@"
}

cmd_sig() {
	COMPOSE_FILE="gen/base-dc.yml:gen/sig-dc.yml" docker-compose "$@"
}

cmd_utils() {
	COMPOSE_FILE="gen/base-dc.yml:gen/utils-dc.yml" docker-compose "$@"
}

cmd_tester() {
	COMPOSE_FILE="gen/base-dc.yml:gen/testers-dc.yml" docker-compose "$@"
}

sig_tester() {
	local ia="$1"
	shift
	docker exec -t "tester_$ia" "$@"
}

cmd_down() {
	cmd_utils down >/dev/null 2>&1
	cmd_sig down >/dev/null 2>&1
	cmd_scion down >/dev/null 2>&1
	FILE="gen/dc-networks.conf"
	while read line; do
		vars=( $line )
		local name="${vars[1]}"
		docker network inspect "$name" &> /dev/null
		if [[ $? -eq 0 ]]; then
			echo "Removing network $(docker network rm "$name")"
		else
			echo "Network $name not found, skip removing."
		fi
	done < $FILE
}

PROGRAM="${0##*/}"
COMMAND="$1"
shift

case "$COMMAND" in
	init|scion|sig|utils|down|tester)
        "cmd_$COMMAND" "$@" ;;
    "run_tester") docker exec -t -e PYTHONPATH=python/: tester "$@" ;;
    "run_sig_tester") sig_tester "$@" ;;
    *)  cmd_help; exit 1 ;;
esac
