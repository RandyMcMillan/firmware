FROM debian:stretch-slim as user
ARG HOST_UID=${HOST_UID:-4000}
ARG HOST_USER=${HOST_USER:-nodummy}
RUN mkdir -p  /home/${HOST_USER} 
RUN [ "${HOST_USER}" == "root" ] || \
    (adduser -h /home/${HOST_USER} -D -u ${HOST_UID} ${HOST_USER} \
    && chown -R "${HOST_UID}:${HOST_UID}" /home/${HOST_USER})
#RUN for u in $(ls /home); do for g in disk lp floppy audio cdrom dialout video netdev games users; do addgroup $u $g; done;done
ARG PASSWORD=${PASSWORD}
RUN echo ${HOST_USER}:${PASSWORD} | chpasswd
RUN echo root:${PASSWORD} | chpasswd
RUN echo "${HOST_USER} ALL=(ALL) ALL" >> /etc/sudoers
RUN echo "root ALL=(ALL) ALL" >> /etc/sudoers
RUN echo "Set disable_coredump false" >> /etc/sudo.conf

WORKDIR /home/${HOST_USER}/firmware/external
RUN apt-get update && \
    apt-get install -y build-essential libffi-dev git pkg-config python python3 && \
    rm -rf /var/lib/apt/lists/* && \
    git clone https://github.com/switck/libngu.git && \
    git clone https://github.com/coinkite/mpy-qr.git && \
    git clone https://github.com/Coldcard/ckcc-protocol.git && \
    git clone https://github.com/Coldcard/micropython.git && \
    cd micropython && \
    git submodule update --init && \
	git submodule foreach --recursive 'git rev-parse HEAD | xargs -I {} git fetch origin {} && git reset --hard FETCH_HEAD' && \
    cd mpy-cross && make && cd .. && \
    cd ports/unix && make axtls && make && make test && make install && \
    apt-get purge --auto-remove -y  build-essential libffi-dev git pkg-config python python3 && \
    cd ../../.. #&& \
    #rm -rf micropython

#CMD ["/usr/local/bin/micropython"]
RUN apt-get update && apt-get upgrade -y && apt-get install --no-install-recommends -y \
	adduser automake \
    bash bash-completion binutils bsdmainutils \
    ca-certificates cmake curl doxygen \
    #diffoscope \
    g++-multilib git \
    libtool libffi6 libffi-dev lbzip2 \
    make nsis \
	openssh-client openssh-server \
    patch pkg-config \
    python3 python3-pip \
    python3-setuptools \
    #ripgrep \
    vim virtualenv \
    xz-utils

RUN rm -f  /usr/bin/python && ln -s /usr/bin/python3 /usr/bin/python
RUN apt-get update && apt-get upgrade -y && apt-get install --no-install-recommends -y \
    imagemagick \
    libbz2-dev libcap-dev libltdl-dev librsvg2-bin libtiff-tools libtinfo5 libz-dev

RUN mkdir -p /home/${HOST_USER}/.ssh &&  chmod 700 /home/${HOST_USER}/.ssh
RUN touch  /home/${HOST_USER}/.ssh/id_rsa
RUN echo -n ${SSH_PRIVATE_KEY} | base64 --decode >  /home/${HOST_USER}/.ssh/id_rsa
RUN  chown -R "${HOST_UID}:${HOST_UID}" /home/${HOST_USER}/.ssh
RUN chmod 600 /home/${HOST_USER}/.ssh/id_rsa

#RUN git clone https://github.com/bitcoin/bitcoin && mkdir bitcoin/depends/SDKs
#RUN make download -C bitcoin/depends
#RUN git clone https://github.com/bitcoin-core/bitcoin-maintainer-tools
# https://github.com/bitcoin/bitcoin/blob/master/doc/build-windows.md#footnotes
#RUN update-alternatives --set x86_64-w64-mingw32-g++ /usr/bin/x86_64-w64-mingw32-g++-posix

RUN apt-get update && apt-get upgrade -y && apt-get install --no-install-recommends -y \
    autotools-dev build-essential libffi-dev git pkg-config python python3
RUN rm -f  /usr/bin/python && ln -s /usr/bin/python3 /usr/bin/python

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
#RUN /usr/bin/python3.8 -m pip install namedlist pyusb click>=6.7 ecdsa>=0.13
#RUN /usr/bin/python3.8 -m pip install hidapi>=0.7.99.post21 pyaes==1.6.1 pytest
#RUN /usr/bin/python3.8 -m pip install pycoin==0.80 mnemonic==0.18 python-bitcoinrpc>=1.0
#RUN /usr/bin/python3.8 -m pip install onetimepass==1.0.1 zbar-py==1.0.4
#
#RUN /usr/bin/python3.8 -m pip install pyserial PySDL2
#RUN /usr/bin/python3.8 -m pip install pyelftools psycopg2 Pillow

#-r ./external/ckcc-protocol/requirements.txt
#-r ./testing/requirements.txt
#-r ./unix/requirements.txt
#
#ckcc-protocol[cli]


