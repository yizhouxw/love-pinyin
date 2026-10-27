#!/bin/sh
set -eu
pretrained_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$pretrained_root"
pretrained_tools="$pretrained_root/tools/pinyin-pretrained"
pretrained_python="$pretrained_tools/.venv/bin/python"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=1
case "${1:-help}" in
  setup) exec uv sync --project "$pretrained_tools" --locked --all-groups ;;
  prepare) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_prepare "$@" ;;
  data) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_data "$@" ;;
  ompal) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_ompal "$@" ;;
  clips) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_ompal_clips "$@" ;;
  cache|train) exec "$pretrained_python" -m pinyin_matcher.pretrained_experiment "$@" ;;
  export) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_export "$@" ;;
  bundle) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_bundle "$@" ;;
  match|info) exec "$pretrained_python" -m pinyin_matcher.pretrained_runtime "$@" ;;
  evaluate|freeze|benchmark) exec "$pretrained_python" -m pinyin_matcher.pretrained_evaluate "$@" ;;
  ensemble) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_ensemble "$@" ;;
  layer-probe) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_layer_probe "$@" ;;
  alignment-v3) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_alignment_v3 "$@" ;;
  factorized) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_factorized "$@" ;;
  chinese-tail) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_chinese_tail "$@" ;;
  chinese-register) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_chinese_register "$@" ;;
  chinese-joint-head) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_chinese_joint_head "$@" ;;
  chinese-report) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_chinese_report "$@" ;;
  xlsr-tail) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_xlsr_tail "$@" ;;
  xlsr-register) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_xlsr_register "$@" ;;
  xlsr-joint-head) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_xlsr_joint_head "$@" ;;
  hard-negative) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_hard_negative "$@" ;;
  hard-negative-strong) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_hard_negative_strong "$@" ;;
  hard-negative-native) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_hard_negative_native "$@" ;;
  hard-negative-eduhk) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_hard_negative_eduhk "$@" ;;
  native-uniform) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_native_uniform "$@" ;;
  tail-finetune) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_tail_finetune "$@" ;;
  aishell3) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_aishell3 "$@" ;;
  native-sequence) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_native_sequence "$@" ;;
  native-clips) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_native_clips "$@" ;;
  native-sequence-export) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_native_sequence_export "$@" ;;
  sequence-adapt) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_sequence_adapt "$@" ;;
  sequence-adapt-config) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_sequence_protocol "$@" ;;
  readout-diagnostics) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_readout_diagnostics "$@" ;;
  native) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_native "$@" ;;
  comparison) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_comparison "$@" ;;
  finetune) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_finetune "$@" ;;
  stress) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_stress "$@" ;;
  iteration-report) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_iteration_report "$@" ;;
  reconstruction-report) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_reconstruction_report "$@" ;;
  report) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_report "$@" ;;
  cold) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_cold "$@" ;;
  ctc) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_ctc_runtime "$@" ;;
  coverage) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_coverage "$@" ;;
  pressure) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_pressure "$@" ;;
  sensevoice-finetune) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_sensevoice_finetune "$@" ;;
  sensevoice-export) shift; exec "$pretrained_python" -m pinyin_matcher.pretrained_sensevoice_export "$@" ;;
  test) exec "$pretrained_python" -m pytest tests/pretrained tests/matcher/test_pretrained_*.py tests/matcher/test_preserved_baseline_cli.py tests/matcher/test_audio.py -q ;;
  *) printf '%s\n' 'Usage: run.sh setup | prepare NAME | data prepare | ompal prepare | clips | cache | train | export | bundle | info | match | evaluate | freeze | benchmark | ensemble | readout-diagnostics | layer-probe | alignment-v3 | factorized | chinese-tail | chinese-register | chinese-joint-head | chinese-report | xlsr-tail | xlsr-register | xlsr-joint-head | hard-negative | hard-negative-strong | hard-negative-native | hard-negative-eduhk | native-uniform | native-clips | tail-finetune | aishell3 | native-sequence | native-sequence-export | sequence-adapt-config | sequence-adapt | native | comparison | finetune | sensevoice-finetune | sensevoice-export | coverage | pressure | ctc | stress | cold | report | iteration-report | reconstruction-report | test' ;;
esac
