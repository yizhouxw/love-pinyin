import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import Ajv2020 from 'ajv/dist/2020.js';

const ajv = new Ajv2020({ allErrors: true });
const manifestSchema = JSON.parse(readFileSync('research/assessment/manifest.schema.json', 'utf8'));
const authorizationSchema = JSON.parse(
  readFileSync('research/assessment/authorization-register.schema.json', 'utf8'),
);
const validateManifest = ajv.compile(manifestSchema);
const validateAuthorization = ajv.compile(authorizationSchema);

const authorizationRegister = {
  schemaVersion: 1,
  datasetId: 'poc-test',
  records: [
    {
      consentRef: 'consent_01',
      cohort: 'target-age-child',
      purpose: 'retained-poc-audio-evaluation',
      approved: true,
      expiresAt: '2099-01-01T00:00:00Z',
      evidenceSha256: 'a'.repeat(64),
    },
  ],
};

describe('评分研究数据契约', () => {
  it('两个 schema 均可编译且授权登记接受最小匿名记录', () => {
    expect(validateManifest).toBeTypeOf('function');
    expect(validateAuthorization(authorizationRegister)).toBe(true);
  });

  it('授权登记拒绝用途扩大、未批准、坏到期时间与额外身份字段', () => {
    for (const invalid of [
      { purpose: 'commercial-product-training' },
      { approved: false },
      { expiresAt: '2099-01-01' },
      { childName: 'must-not-be-present' },
    ]) {
      const candidate = structuredClone(authorizationRegister);
      Object.assign(candidate.records[0], invalid);
      expect(validateAuthorization(candidate)).toBe(false);
    }
  });
});
