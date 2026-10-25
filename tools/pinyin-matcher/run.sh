#!/bin/sh
set -eu
matcher_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$matcher_root"
matcher_tools="$matcher_root/tools/pinyin-matcher"
matcher_python="$matcher_tools/.venv/bin/python"
if [ ! -x "$matcher_python" ] && [ -x "$matcher_tools/.runtime/bin/python" ]; then
  matcher_python="$matcher_tools/.runtime/bin/python"
fi
# Feature extraction and ORT run sequentially. Bound BLAS independently of ORT.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
case "${1:-help}" in
  setup)
    uv sync --project "$matcher_tools" --locked --all-groups
    ;;
  setup-runtime)
    UV_PROJECT_ENVIRONMENT="$matcher_tools/.runtime" uv sync --project "$matcher_tools" --locked --no-default-groups
    ;;
  install)
    shift
    "$matcher_python" -m pinyin_matcher.package "$@"
    ;;
  build)
    shift
    "$matcher_python" -m pinyin_matcher.build "$@"
    ;;
  prepare-generators)
    UV_PROJECT_ENVIRONMENT="$matcher_root/private/matcher-qwen-env" uv sync --locked --only-group voice-build
    uv sync --project "$matcher_tools/cosyvoice" --locked
    "$matcher_python" -m pinyin_matcher.prepare qwen
    "$matcher_python" -m pinyin_matcher.prepare cosy
    ;;
  match|targets|info)
    "$matcher_python" -m pinyin_matcher "$@"
    ;;
  train|evaluate|merge)
    "$matcher_python" -m pinyin_matcher.train "$@"
    ;;
  test)
    "$matcher_python" -m pytest tests/matcher -q
    ;;
  *)
    printf '%s\n' 'Usage: run.sh setup | setup-runtime | prepare-generators | install --source DIR --destination DIR | targets | info --model DIR | match --model DIR --target ID --wav FILE | build --manifest FILE --output DIR --cache-dir DIR | train --manifest FILE --output DIR | evaluate --manifest FILE --output DIR | merge INPUTS --output FILE | test'
    ;;
esac
