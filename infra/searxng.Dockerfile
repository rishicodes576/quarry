FROM searxng/searxng@sha256:5ed0323b5f5f8701264ef65e239a2bd83cb57098f2b971fa30bf79c06eeae271
USER root
ADD --checksum=sha256:42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b https://files.pythonhosted.org/packages/c4/51/29046e48f693c54e5b7412216d447a1d8362c9653148d98c02cdf65fa733/certifi-2026.10.19-py3-none-any.whl /tmp/certifi.whl
RUN /usr/local/searxng/.venv/bin/python -c "import sysconfig,pathlib,shutil,zipfile; p=pathlib.Path(sysconfig.get_paths()['purelib']); [shutil.rmtree(x) for x in p.glob('certifi*') if x.is_dir()]; zipfile.ZipFile('/tmp/certifi.whl').extractall(p)" && rm /tmp/certifi.whl

USER 977:977
