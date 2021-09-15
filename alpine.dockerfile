ARG ALPINE_VERSION=${ALPINE_VERSION}
#FROM alpine:${ALPINE_VERSION} as base
FROM alpine:${ALPINE_VERSION} as user

RUN apk update \
    && apk add ${VERBOSE} ${NO_CACHE} \
        alpine-sdk sudo bash-completion git vim curl shadow openssh-client

#FROM scratch as user
#COPY --from=base . .

RUN apk update \
    && apk add ${VERBOSE} ${NO_CACHE} \
        python3 python3-dev py3-pip py3-virtualenv py3-numpy-dev \
        libzbar hidapi libusb-dev eudev-dev linux-headers \
        gcc libtool automake autoconf libffi pkgconf bsd-compat-headers build-base

RUN apk update \
    && apk add --virtual build-deps gcc python3-dev musl-dev \
    && apk add gcc make openssl libressl-dev musl-dev build-base libffi-dev \
    && apk add postgresql \
    && apk add postgresql-dev \
    && apk add jpeg-dev zlib-dev libjpeg

ARG HOST_UID=${HOST_UID:-4000}
ARG HOST_USER=${HOST_USER:-nodummy}

RUN [ "${HOST_USER}" == "root" ] || \
    (adduser -h /home/${HOST_USER} -D -u ${HOST_UID} ${HOST_USER} \
    && chown -R "${HOST_UID}:${HOST_UID}" /home/${HOST_USER})

RUN for u in $(ls /home); do for g in disk lp floppy audio cdrom dialout video netdev games users; do addgroup $u $g; done;done

ARG PASSWORD=${PASSWORD}
RUN echo ${HOST_USER}:${PASSWORD} | chpasswd
RUN echo root:${PASSWORD} | chpasswd
RUN echo "${HOST_USER} ALL=(ALL) ALL" >> /etc/sudoers
RUN echo "root ALL=(ALL) ALL" >> /etc/sudoers
RUN echo "Set disable_coredump false" >> /etc/sudo.conf

#USER ${HOST_USER}
#WORKDIR /home/${HOST_USER}
#WORKDIR /home/${HOST_USER}/firmware
#COPY ENV/bin /usr/local/bin
#COPY /home/${HOST_USER}/firmware/ENV/bin/ /usr/local/bin
#COPY /home/${HOST_USER}/firmware/ENV/include/ /usr/local/include
#RUN mkdir -p /usr/local/lib
#COPY /home/${HOST_USER}/firmware/ENV/lib/ /usr/local/lib

RUN mkdir -p /home/${HOST_USER}/.ssh &&  chmod 700 /home/${HOST_USER}/.ssh
#COPY ${HOME}/.ssh/id_rsa /home/${HOST_USER}/.ssh/id_rsa
#RUN chmod 600 /home/${HOST_USER}/.ssh/id_rsa

WORKDIR /home/${HOST_USER}/firmware
RUN git init
RUN git submodule update --init
RUN git submodule foreach --recursive 'git rev-parse HEAD | xargs -I {} git fetch origin {} && git reset --hard FETCH_HEAD'
#WORKDIR /home/${HOST_USER}/firmware/external/libwally-core
#RUN cd external/libwally-core
#RUN autoreconf --install --force --warnings=all
#RUN chmod +x /home/root/firmware/external/libwally-core/tools/autogen.sh
#RUN ./configure && make && make install

WORKDIR /home/${HOST_USER}/firmware
RUN /usr/bin/python3.8 -m pip install namedlist pyusb click>=6.7 ecdsa>=0.13
RUN /usr/bin/python3.8 -m pip install hidapi>=0.7.99.post21 pyaes==1.6.1 pytest
RUN /usr/bin/python3.8 -m pip install pycoin==0.80 mnemonic==0.18 python-bitcoinrpc>=1.0
RUN /usr/bin/python3.8 -m pip install onetimepass==1.0.1 zbar-py==1.0.4

RUN /usr/bin/python3.8 -m pip install pyserial PySDL2
RUN /usr/bin/python3.8 -m pip install pyelftools psycopg2 Pillow

#-r ./external/ckcc-protocol/requirements.txt
#-r ./testing/requirements.txt
#-r ./unix/requirements.txt
#
#ckcc-protocol[cli]


