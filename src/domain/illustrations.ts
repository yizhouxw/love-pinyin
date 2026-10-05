export type IllustrationCatalog = {
  version: number;
  intro: string;
  items: Record<
    string,
    {
      name: string;
      pinyin: string;
      lessonId: string;
      audioRef: string;
      description: string;
    }
  >;
};
