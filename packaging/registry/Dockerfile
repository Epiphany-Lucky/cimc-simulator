# OCI delivery envelope for installers, not a runnable simulator container.
FROM scratch
ARG VERSION
ARG PLATFORM
LABEL org.opencontainers.image.source="https://github.com/Epiphany-Lucky/cimc-simulator" \
      org.opencontainers.image.url="https://github.com/Epiphany-Lucky/cimc-simulator/releases" \
      org.opencontainers.image.title="CIMC Studio installers" \
      org.opencontainers.image.description="Downloadable desktop installation files; extract /packages or use GitHub Releases." \
      org.opencontainers.image.version="${VERSION}" \
      io.cimc.delivery.platform="${PLATFORM}"
COPY packages/ /packages/
