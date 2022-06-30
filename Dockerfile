FROM python:3.9.13-bullseye
RUN apt-get update
RUN apt-get install -y libgfortran5 libatlas3-base
