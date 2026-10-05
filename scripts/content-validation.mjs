import Ajv from 'ajv';

export function validateCurriculum(data, schema, { sourceIds = [], release = false } = {}) {
  const errors = [];
  const validate = new Ajv({ allErrors: true, strict: true }).compile(schema);
  if (!validate(data)) return validate.errors.map((e) => `${e.instancePath}: ${e.message}`);
  const assert = (condition, message) => {
    if (!condition) errors.push(message);
  };
  const collection = (rows, name) => {
    const map = new Map();
    for (const row of rows) {
      assert(!map.has(row.id), `${name}: duplicate id ${row.id}`);
      map.set(row.id, row);
    }
    return map;
  };
  const lessons = collection(data.lessons, 'lessons');
  const knowledge = collection(data.knowledgeItems, 'knowledge');
  const questions = collection(data.exercises, 'exercises');
  const targets = collection(data.readingTargets, 'readingTargets');
  const audio = collection(data.audioRequirements, 'audio');
  const expectedInventories = {
    initial: data.inventory.initials,
    final: data.inventory.finals,
    'whole-syllable': data.inventory.wholeSyllables,
    'orthographic-letter': data.inventory.orthographicLetters,
  };
  for (const [category, symbols] of Object.entries(expectedInventories)) {
    const actual = data.knowledgeItems
      .filter((k) => k.category === category)
      .map((k) => k.symbol)
      .sort();
    assert(
      JSON.stringify(actual) === JSON.stringify([...symbols].sort()),
      `inventory mismatch: ${category}`,
    );
  }
  assert(
    data.inventory.initials.length === 21 && data.inventory.orthographicLetters.join(' ') === 'y w',
    '2024 edition: 21 initials plus y/w expected',
  );
  assert(
    data.inventory.finals.length === 24 && data.inventory.wholeSyllables.length === 16,
    '2024 edition: 24 finals / 16 whole syllables expected',
  );
  const checkRefs = (refs, map, label) =>
    refs.forEach((id) => assert(map.has(id), `${label}: unknown ${id}`));
  const knownSources = new Set(sourceIds);
  for (const row of [
    data,
    ...data.lessons,
    ...data.knowledgeItems,
    ...data.exercises,
    ...data.readingTargets,
  ]) {
    checkRefs(row.sourceIds, knownSources, `${row.id} sources`);
  }
  const visiting = new Set();
  const visited = new Set();
  function visit(id) {
    if (visiting.has(id)) {
      errors.push(`prerequisite cycle: ${id}`);
      return;
    }
    if (visited.has(id) || !lessons.has(id)) return;
    visiting.add(id);
    for (const dep of lessons.get(id).prerequisiteLessonIds) visit(dep);
    visiting.delete(id);
    visited.add(id);
  }
  const orders = new Set();
  for (const lesson of data.lessons) {
    assert(!orders.has(lesson.order), `duplicate lesson order ${lesson.order}`);
    orders.add(lesson.order);
    checkRefs(lesson.prerequisiteLessonIds, lessons, lesson.id);
    checkRefs(lesson.knowledgeIds, knowledge, lesson.id);
    checkRefs(lesson.exerciseIds, questions, lesson.id);
    checkRefs(lesson.readingTargetIds, targets, lesson.id);
    for (const id of lesson.exerciseIds)
      assert(questions.get(id)?.lessonId === lesson.id, `${id}: lesson mismatch`);
    for (const id of lesson.readingTargetIds)
      assert(targets.get(id)?.lessonId === lesson.id, `${id}: reading lesson mismatch`);
    for (const id of lesson.prerequisiteLessonIds)
      assert(
        (lessons.get(id)?.order ?? Infinity) < lesson.order,
        `${lesson.id}: prerequisite must precede lesson`,
      );
    visit(lesson.id);
  }
  for (const k of data.knowledgeItems) {
    assert(lessons.has(k.lessonId), `${k.id}: unknown lesson`);
    assert(lessons.get(k.lessonId)?.knowledgeIds.includes(k.id), `${k.id}: missing from lesson`);
    checkRefs(k.confusableIds, knowledge, k.id);
    const primary = data.exercises.filter((q) => q.primaryKnowledgeId === k.id);
    assert(primary.length > 0, `${k.id}: no primary exercise`);
    for (const mode of k.requiredModes)
      assert(
        primary.some((q) => q.type === mode),
        `${k.id}: required mode ${mode} uncovered`,
      );
  }
  for (const q of data.exercises) {
    checkRefs(q.knowledgeIds, knowledge, q.id);
    assert(q.knowledgeIds.includes(q.primaryKnowledgeId), `${q.id}: primary knowledge missing`);
    assert(lessons.get(q.lessonId)?.exerciseIds.includes(q.id), `${q.id}: missing from lesson`);
    if (q.audioRef) assert(audio.has(q.audioRef), `${q.id}: unknown audio`);
    assert(audio.has(q.promptAudioRef), `${q.id}: unknown prompt audio`);
    for (const option of q.options) {
      if (option.audioRef) assert(audio.has(option.audioRef), `${q.id}: unknown option audio`);
      if (/\p{Script=Han}/u.test(option.label))
        assert(!!option.audioRef, `${q.id}: Chinese option needs narration`);
    }
    assert(
      (knowledge.get(q.primaryKnowledgeId)?.lessonId &&
        lessons.get(knowledge.get(q.primaryKnowledgeId).lessonId)?.order) <=
        lessons.get(q.lessonId)?.order,
      `${q.id}: primary knowledge taught later`,
    );
    if (['listen-choice', 'read-aloud'].includes(q.type))
      assert(!!q.audioRef, `${q.id}: audio required`);
    if (q.type === 'read-aloud') {
      assert(targets.has(q.answer.readingTargetId), `${q.id}: unknown reading target`);
      assert(
        targets.get(q.answer.readingTargetId)?.lessonId === q.lessonId,
        `${q.id}: reading target lesson mismatch`,
      );
      assert(
        targets.get(q.answer.readingTargetId)?.audioRef === q.audioRef,
        `${q.id}: reading audio mismatch`,
      );
      assert(q.options.length === 0, `${q.id}: reading cannot be choice`);
    } else {
      const options = new Set(q.options.map((o) => o.id));
      assert(options.size === q.options.length && options.size >= 2, `${q.id}: invalid options`);
      assert(
        new Set(q.options.map((o) => o.label)).size === q.options.length,
        `${q.id}: duplicate option labels`,
      );
      assert(options.has(q.answer.optionId), `${q.id}: answer not in options`);
    }
  }
  for (const r of data.readingTargets) {
    checkRefs(r.knowledgeIds, knowledge, r.id);
    assert(
      lessons.get(r.lessonId)?.readingTargetIds.includes(r.id),
      `${r.id}: missing from lesson`,
    );
    assert(
      r.targetType === 'syllable'
        ? r.syllables.length > 0
        : r.syllables.length === 0 && !!r.phoneme,
      `${r.id}: invalid target type payload`,
    );
    assert(r.knowledgeIds.includes(r.primaryKnowledgeId), `${r.id}: reading primary missing`);
    assert(audio.has(r.audioRef), `${r.id}: reading audio missing`);
    if (r.targetType === 'isolated-initial')
      assert(r.phoneme?.tone === null, `${r.id}: initial has no tone`);
  }
  for (const a of data.audioRequirements) {
    checkRefs(a.knowledgeIds, knowledge, a.id);
  }

  function checkUnicode(value) {
    if (typeof value === 'string')
      assert(value === value.normalize('NFC'), `non-NFC string: ${value}`);
    else if (Array.isArray(value)) value.forEach(checkUnicode);
    else if (value && typeof value === 'object') Object.values(value).forEach(checkUnicode);
  }
  checkUnicode(data);
  // These authoring summaries ship with the content and must not silently keep
  // the old seed-bank numbers when exercises are added or removed.
  const coverage = data.coverage;
  if (coverage) {
    assert(coverage.exerciseCount === data.exercises.length, 'coverage: stale exercise count');
    assert(
      coverage.objectiveExerciseCount ===
        data.exercises.filter((q) => q.type !== 'read-aloud').length,
      'coverage: stale objective exercise count',
    );
    assert(
      coverage.audioRequirementCount === audio.size,
      'coverage: stale audio requirement count',
    );
    for (const k of data.knowledgeItems) {
      const primary = data.exercises.filter((q) => q.primaryKnowledgeId === k.id);
      assert(
        coverage.primaryExerciseCounts?.[k.id] === primary.length &&
          coverage.objectivePrimaryExerciseCounts?.[k.id] ===
            primary.filter((q) => q.type !== 'read-aloud').length,
        `coverage: stale primary count for ${k.id}`,
      );
    }
  }
  if (release) {
    assert(
      data.edition.latestRevisionPinyinClauses === 'verified',
      'release: latest curriculum clauses need primary-text verification',
    );
    assert(
      data.knowledgeItems.every(
        (k) =>
          data.exercises.filter((q) => q.primaryKnowledgeId === k.id && q.type !== 'read-aloud')
            .length >= 5,
      ),
      'release: seed bank needs at least 5 distinct objective primary exercises per knowledge item',
    );
    assert(
      [1, 2, 3, 4].every((tone) =>
        data.exercises.some(
          (q) =>
            ['tone-choice', 'listen-choice'].includes(q.type) &&
            q.audioRef &&
            q.primaryKnowledgeId === `k-tone-${tone}`,
        ),
      ),
      'release: auditory coverage for all four tones missing',
    );
  }
  return errors;
}
