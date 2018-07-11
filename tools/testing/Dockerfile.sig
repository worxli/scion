FROM alpine

WORKDIR /share

RUN apt update && apt install libcap2-bin iproute2 iputils-ping tcpdump -y

COPY sig.sh .

RUN mkdir -p /etc/iproute2
RUN chmod +x sig.sh

COPY --from=scion_app_base:latest /sbin/su-exec /sbin/su-exec
COPY --from=scion_app_builder:latest /home/scion/go/src/github.com/scionproto/scion/bin/sig /app/
RUN ["setcap", "cap_net_admin+ei", "/app/sig"]
# Note: this process needs explicit CAP_NET_ADMIN from docker. e.g. with `cap_add: NET_ADMIN` from docker-conmpose
ENTRYPOINT ["./sig.sh"]
