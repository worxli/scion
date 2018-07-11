#!/bin/bash

set -ex

SIG="$1"
shift

ip route

for net in $(echo $1 | tr , ' '); do
    ip route add "$net" via $SIG dev eth0
done

tail -f /dev/null
