# Video production architecture

This public repository contains two Hermes profile packages: [VIC Creator](../agents/vic-creator/README.md) and [VIC Voice](../agents/vic-voice/README.md).

Creator's main model plans the beginner explanation, story, visual actions, pacing and sound. Bounded execution workers implement specified evidence/asset/scene packets. The main integrates artifacts, runs technical checks and reviews the encoded result. Voice is a shared procedure/driver that can also run independently.

Brief → script/storyboard → owner approval → voice sample/review → measured narration → scene/assets/sound execution → real-audio proof/approval → full render → main review/fixes → owner final acceptance. Publishing remains separate.

See [the detailed approach and diagram](VIDEO_PRODUCTION.md), [setup](VIDEO_SETUP.md) and [published sample gallery](VIDEO_SAMPLES.md). Private recordings, accounts and operational job state remain outside this public source package.
