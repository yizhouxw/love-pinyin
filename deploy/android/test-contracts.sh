#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the authorized device serial}"
adb_bin="${ANDROID_HOME:-$HOME/Library/Android/sdk}/platform-tools/adb"
uv run --locked python -m deploy.android.contracts
node_modules/.bin/prettier --write deploy/android/app/src/androidTest/assets/contracts.json
./deploy/android/build.sh --offline :app:assembleDebugAndroidTest
"$adb_bin" -s "$ANDROID_SERIAL" install --no-streaming -r deploy/android/app/build/outputs/apk/debug/app-debug.apk
"$adb_bin" -s "$ANDROID_SERIAL" install --no-streaming -r deploy/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
mkdir -p build/android/verification
"$adb_bin" -s "$ANDROID_SERIAL" shell am instrument -w org.lovepinyin.android.test/org.lovepinyin.android.ContractInstrumentation | tee build/android/verification/contracts.txt
rg -q '^ANDROID_CONTRACT_OK:' build/android/verification/contracts.txt
