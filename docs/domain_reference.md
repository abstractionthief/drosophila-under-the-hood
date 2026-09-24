# Domain reference: MaleCNS biology and neuroanatomy

A glossary and biological context for this project. Other documents in
`docs/` describe *what we built* (`project_overview.md`) and *how we
classify the data* (`io_classification_rules.md`) — this one describes
*what all of this is about, biologically*.

**Important distinction used throughout this document:**
- 🔵 **[general knowledge]** — established *Drosophila* neuroanatomy
  from the scientific literature, independent of our dataset.
- 🟢 **[our data]** — concrete numbers/facts from `male-cns:v1.0` that we
  actually computed in this project.

We never mix these two categories without marking them — exactly as in
`docs/io_classification_rules.md` for the nerve mapping.

---

## 1. What a connectome is, and what MaleCNS is

**Connectome** 🔵 — a complete map of synaptic connections between
neurons in a given nervous system. Unlike classical neuroanatomy (which
shows regions and pathways approximately), an electron-microscopy (EM)
connectome gives a **reconstructed, automatically detected count of
synapses** between every pair of neurons — more precise than traditional
neuroanatomy, but not the same as manually verified certainty on every
body (see the `Traced` status below).

**MaleCNS (`male-cns:v1.0`)** 🔵 — a Janelia Research Campus project: a
connectome of the **central nervous system (CNS) of an adult male
*Drosophila melanogaster*** (fruit fly) — brain + ventral nerve cord
(VNC) combined in a single EM dataset. This sets it apart from older,
partial datasets:
- **hemibrain** 🔵 — brain only (no VNC), a partial (not whole-brain)
  reconstruction of a **female** (confirmed: [FlyEM / Hemibrain, Janelia
  Research Campus](https://www.janelia.org/project-team/flyem/hemibrain)).
- **MANC** (Male Adult Nerve Cord) 🔵 — male VNC only.
- **FlyWire** 🔵 — a whole female brain (whole-brain, not whole-CNS).

MaleCNS combines the brain and VNC of one adult male fly, so our network
covers both brain processing and local body/motor circuits in one graph.

🟢 **In our data:** 211,579 DVID-annotated bodies, of which 165,122 have
status `Traced`. This is an operational filter of the reconstruction
process, not a uniform completeness guarantee — among `Traced` bodies,
`statusLabel` is `Roughly traced` for 71,979 and `Prelim Roughly traced`
for another 36,387 (together roughly 2/3 of all `Traced`). These workflow
annotations do not establish whether proofreading is currently active.

---

## 2. Fly CNS anatomy — three main regions

🔵 **[general knowledge, established in the literature]**

### 2.1 Optic lobe
A pair of structures on either side of the brain, directly behind the
compound eyes, made up of four neuropils: **lamina, medulla, lobula,
lobula plate**. This is the **single largest processing structure** in
the fly brain by neuron count — the fly "thinks" with vision in a very
literal, volumetric sense.

Signal flow **is not one serial chain** lamina→medulla→lobula→lobula
plate — that's an oversimplification. R1-R6 photoreceptors (brightness,
contrast) do synapse first in the lamina, but R7/R8 (color) bypass the
lamina and project straight to the medulla. From the medulla, signal
fans out along several **parallel** pathways: the lobula plate
specializes in motion detection (home to the famous LPTC cells, e.g.
HS/VS), the lobula in shape/form — this isn't lobula "before" lobula
plate in one line, but two partially independent, partially
cross-talking processing streams out of the medulla.

🟢 **In our data:** `ol_intrinsic` (neurons within the optic lobe) is
89,403 neurons — **42% of the entire raw census**, more than any other
single type.

### 2.2 Central brain
The integrative region, containing among others:
- **Mushroom body** 🔵 — the memory and learning center (especially
  associative learning, e.g. odor↔reward). Kenyon cells are the main
  cell type of this structure.
- **Central complex** 🔵 — spatial navigation, the fly's "compass",
  integrating heading direction with visual orientation.
- **Lateral horn** 🔵 — "innate" (non-learned) processing of smell, e.g.
  avoiding odors that signal danger.
- **Antennal lobes** 🔵 — the first stop for olfactory signal from the
  antennae, where ORN (olfactory receptor neurons) synapse onto PN
  (projection neurons), which send the signal on to the mushroom body
  and lateral horn.

🟢 **In our data:** `cb_intrinsic` = 32,164 neurons. We saw a concrete
example of this pathway: neuron 10039 (`VL2a_adPN`) is exactly a PN
receiving signal from `ORN_VL2a` and sending it onward.

### 2.3 Ventral nerve cord (VNC)
🔵 The vertebrate spinal cord's counterpart. In the adult fly, **the
ganglion itself is consolidated in the thorax** — unlike many other
insects, the thoracic and abdominal neuromeres are fused into one
structure physically located in the thorax, not distributed segmentally
through the abdomen. Nerves from this ganglion control the legs, wings,
and abdomen even though the ganglion itself doesn't reach there.
Functionally divided into **neuromeres** — segmental units corresponding
to pairs of legs/wings:

| neuromere | controls |
|---|---|
| T1 (prothoracic) | front leg |
| T2 (mesothoracic) | middle leg + wing |
| T3 (metathoracic) | hind leg + haltere |
| A1-A9/A10 (abdominal) | abdomen |

🔵 **GNG (gnathal ganglion) isn't another VNC segment in the same
sense** — it's the fused mandibular/maxillary/labial neuromeres,
anatomically located in the ventral part of the *brain* (subesophageal
zone), at the brain-VNC boundary, not in the thoracic ganglion mass
alongside T1-T3/A1-A9. It controls the mouthparts/proboscis and is kept
separate from the thoracic and abdominal neuromeres in the table above.

🟢 **In our data:** the `somaNeuromere` column encodes exactly this —
T2 (5,076), T1 (4,296), T3 (3,976) are the most common, then the
abdominal segments A1-A9.

---

## 3. Cell-type taxonomy — how the dataset describes a neuron

🟢 The `superclass` field (the most reliable, ~99.7% coverage for
`Traced` neurons) splits neurons by **functional role**, not directly by
anatomical location:

| superclass | role |
|---|---|
| `ol_intrinsic` | processing within the optic lobe |
| `cb_intrinsic` | processing within the central brain |
| `vnc_intrinsic` | processing within the VNC |
| `visual_projection` | OL → central brain relay |
| `visual_centrifugal` | central brain → OL relay (feedback!) |
| `*_sensory` | primary sensory transduction |
| `ascending_neuron` | VNC → brain (feedback from the body) |
| `descending_neuron` | brain → VNC (motor commands) |
| `*_motor` | direct muscle control |
| `*_endocrine` | neurohormone secretion |
| `ENS` | enteric nervous system — the gut's nervous system, partly autonomic |

`class`/`subclass` is a finer split *within* superclass — e.g. for
sensory neurons `class` states specifically *which* sense (`olfactory`,
`visual`, `gustatory`...); for **central brain** neurons (`cb_intrinsic`)
`class` can be e.g. `Kenyon_Cell`, `CX` (central complex) — these
structures belong to the central brain (section 2.2), not the optic lobe.

---

## 4. Sensory modalities (input_category)

🔵 **[general knowledge of sensory organs]** + 🟢 **[our numbers]**

| modality | sensory organ | 🟢 neuron count |
|---|---|---|
| `vision` | compound eyes (photoreceptors → OL) | 6,091 |
| `mechanosensation` | touch bristles, sensors across the body | 4,291 |
| `olfaction` | antennae, ORNs | 2,639 |
| `proprioception` | muscle/joint tension receptors ("where are my legs") | 1,453 |
| `gustation` | taste receptors (labellum, legs — the fly "tastes with its feet") | 1,428 |
| `hygrosensation` | air humidity | 66 |
| `other_sensory` (chemosensory) | unspecified chemosensation - the dataset doesn't separately label it as smell or taste, which isn't the same as excluding either | 58 |
| `thermosensation` | temperature | 25 |

🔵 An unresolved detail in our classification: **hearing (audition)** in
*Drosophila* isn't a separate organ the way it is in mammals — it works
through **Johnston's organ** in the second antennal segment, which
detects air vibration via movement of the antenna itself. This means
"hearing" is biologically a subtype of antennal mechanosensation, not a
separate modality — hence `auditory_antennal` has no dedicated `class`
field in our data and is folded into `mechanosensation` (see the open
question in `docs/io_classification_rules.md`, section 2).

---

## 5. Output categories (output_category)

🟢 Priority: `subclass` for motor neurons (directly encodes the target
muscle group), `exitNerve` as a fallback for the rest (lower confidence,
based on external MANC nerve nomenclature) — see
`io_classification_rules.md` section 3. **Corrected after an external
domain review**, which found that the version based solely on
`exitNerve` misassigned at least 63 motor neurons (among other things,
it completely excluded `haltere` from its own neurons):

| category | 🟢 count | 🔵 biological context |
|---|---|---|
| `abdomen` | 295 | abdominal muscles; in the male, includes the copulatory apparatus |
| `front_leg` | 141 | walking, grooming, first tactile-gustatory contact — the male taps the female's abdomen with a front leg ("tapping") as the first step of courtship |
| `hind_leg` | 131 | walking, stabilization |
| `middle_leg` | 117 | walking, stabilization |
| `wing` | 76 | flight, but also the courtship song (unilateral wing vibration - "pulse song"; this is not stridulation, which in insects means sound from rubbing body parts together, a different mechanism than the fly uses) |
| `endocrine` | 71 | **not movement** — hormone secretion (e.g. to the corpora cardiaca/allata) |
| `proboscis` | 67 | mouthparts, feeding |
| `neck` | 45 | head stabilization relative to the body during flight/movement |
| `haltere` | 18 | the "gyroscope" — modified hindwings that detect Coriolis forces during flight and feed back into wing/neck muscle control |
| `other_motor` | 15 | unclassified |

🔵 **Haltere deserves its own note** — it's one of the best-studied
microcircuits in insect neuroscience: it vibrates at the same frequency
as the wings, and the inertial (Coriolis) forces acting on it during body
turns are detected by a sensor field at its base and translated in real
time into flight corrections. 18 neurons in our data's `haltere` category
is still few compared to other output categories — of which exactly
**16 are genuinely motor neurons** (`subclass == "hm"`), and the
remaining **2 are other (non-motor) efferent neurons** exiting through
the same nerve (`DMetaN`), included here via the `exitNerve` fallback,
not the motor rule. This isn't a complete description of the
sensorimotor circuit (haltere sensors/interneurons live elsewhere in the
classification) — we don't draw any conclusion from it about the size of
the full reflex.

---

## 6. Neurotransmitters — functional role

🔵 **[general knowledge]** + 🟢 **[coverage in our data]**

| neurotransmitter | 🔵 typical role in *Drosophila* | 🟢 neuron count |
|---|---|---|
| acetylcholine (ACh) | **excitatory**, dominant in the fly CNS (opposite of mammals, where that's glutamate) | 104,173 |
| glutamate | **receptor-dependent** — can be excitatory or inhibitory (GluCl receptors are inhibitory!) | 29,443 |
| GABA | **inhibitory**, the main inhibitory NT | 22,186 |
| histamine | **inhibitory**, mainly in photoreceptors (atypical for a sensory NT) | 8,024 |
| dopamine | modulatory — motivation, learning, arousal state | 396 |
| octopamine | modulatory — the insect counterpart of noradrenaline, "fight or flight" | 101 |
| serotonin (5-HT) | modulatory — sleep, appetite, aggression | **48** |

⚠️ **Important caveat for any future dynamics/simulation work:**
glutamate in *Drosophila* is NOT unambiguously excitatory — it depends
on the postsynaptic receptor type (GluCl = chloride channel = inhibitory,
other receptors = excitatory), and this isn't resolved in our data (we
don't have the postsynaptic receptor type). A simple "sign of weight =
sign of neurotransmitter" model therefore assigns a sign that these data
cannot resolve for glutamatergic connections. The share of glutamatergic
neurons is not a measurable model-error percentage: the error rate would
require receptor or functional evidence. This is one of the key
limitations before building any dynamics model.

---

## 7. Directionality: ascending vs. descending

🔵 This distinction is fundamental in insect (and vertebrate)
neuroscience:

- **descending neurons (DN)** — brain → VNC. These are "commands": the
  brain decides "run", "turn", "flee", DNs carry that decision down to
  the VNC's motor circuits, which then break it down into specific
  muscle contractions. The fly has relatively **few** DNs (🟢 1,314 in
  our data) compared to the size of the VNC that executes them — this
  suggests the VNC has substantial autonomy: the brain sends terse
  "high-level commands", and the execution details (coordinating 6 legs,
  contraction timing) are worked out locally in the VNC.
- **ascending neurons (AN)** — VNC → brain. Feedback: leg position
  (proprioception), touch, movement-execution state. The brain "knows"
  what the body is doing thanks to these neurons.

🔵 The most famous single DN in the literature: the **Giant Fiber
(DNp01)** — the neuron responsible for the escape reflex (a lightning-fast
jump + flight takeoff in response to an approaching shadow/threat), one
of the fastest and best-described circuits in insects.

🟢 **We have it in our data**: bodyid 10001, `DNp01(GF)_R`,
neurotransmitter acetylcholine — this exact neuron already came up in
this project's early exploration.

---

## 8. Synapses and connection "weight" — what it actually means

🔵 In electron-microscopy data, the `weight` between two neurons is the
**number of identified synapses** between them (not the strength of a
single synapse, not frequency, not voltage). One neuron can have
hundreds of synapses with another (weight 300+), or just one (weight 1).

🔵 **Why this isn't the same as "signal strength":**
- More synapses usually correlates with stronger functional influence,
  but not linearly and not always — it depends on receptor type, the
  synapse's location on the dendritic tree, and plasticity.
- Weight is **static** (measured once, from a single EM sample) — it
  doesn't account for neuromodulation, adaptation, or the fly's
  physiological state at any given moment.
- That's why, throughout this project (from Phase 6 onward), weight is
  consistently treated as a **topological measure**, not biological
  signal strength — this isn't excessive caution, it's a fundamental
  limitation of data from a single EM reconstruction.

🔵 **ROI (region of interest)** — the dataset additionally knows *in
which anatomical region* (e.g. a specific antennal-lobe glomerulus, a
specific medulla layer) a given synapse is located - we haven't used
this field in this project yet (`by.roi` exists in `neuprintr` queries,
but hasn't been used).

---

## 9. Reconstruction status and confidence

🔵 EM connectome reconstruction is a partly automated, partly
manually-verified process — hence the `status` field:

| status | meaning |
|---|---|
| `Traced` | an operational filter of the reconstruction process, **not** a guarantee of full verification — among `Traced`, `statusLabel` is `Roughly traced`/`Prelim Roughly traced` for roughly 2/3 of all of them (see section 1) |
| `Orphan` | a fragment with no clear assignment to a larger structure |
| `Glia` | a glial cell (not a neuron — supports/insulates neurons, doesn't conduct signal the way a neuron does) |
| `Assign` | assigned, but not fully verified |
| `Anchor` | a reconstruction anchor point |
| `Unimportant` | skipped as not relevant to the main network |

🟢 Hence our earlier discrepancy: "~166k neurons" is `Traced`, while 211k
is everything taken together, including glia and fragments.

---

## 10. Known functional circuits — what's described in the literature

🔵 A few well-documented, named circuits in *Drosophila* that could serve
as reference points for future work on specific behaviors (we haven't
verified their presence/completeness in our data - this is a list *to
check*, not confirmed facts about our dataset):

- **Giant Fiber / DNp01** — the escape reflex. **Confirmed in our data**
  (bodyid 10001).
- **P1 neurons** — courtship initiation in the male (hence particularly
  relevant to MaleCNS as a male dataset) — we haven't checked their
  presence yet.
- **mAL neurons / fruitless circuit** — a circuit determining sex-specific
  behaviors (the *fruitless* gene), strongly tied to `dimorphism` (a
  field we have in the census - 1,258 neurons labeled `male-specific`).
- **Central complex compass neurons** (e.g. E-PG) — the navigational
  "compass".
- **Mushroom body output neurons (MBON) / dopaminergic input neurons
  (DAN)** — the associative-learning circuit. 🟢 We've seen both types as
  `class` values in our census (`MBON` 97, `DAN` 340).

If we wanted to move toward "behavioral function" as a future direction,
this is the way: look for `type`/`name` values matching these known
circuits and verify their actual presence/structure in `male-cns:v1.0`.

---

## 11. Glossary of abbreviations used in the data

| abbreviation | expansion |
|---|---|
| ORN | olfactory receptor neuron |
| PN | projection neuron |
| LN | local interneuron (doesn't leave its region) |
| MBON | mushroom body output neuron |
| DAN | dopaminergic neuron (input to the mushroom body) |
| DN | descending neuron |
| AN | ascending neuron |
| ALPN / ALLN | antennal lobe projection/local neuron |
| CX | central complex |
| GF | Giant Fiber |
| VNC | ventral nerve cord |
| OL | optic lobe |
| CB | central brain |
| DVID | a distributed database for volumetric imaging data (the storage system behind the EM segmentation) |
| EM | electron microscopy — the imaging method the whole connectome is built on |

---

## Sources for this general knowledge

Facts marked 🔵 come from the established *Drosophila* neuroscience
literature (Janelia/FlyWire/MANC publications, textbook insect anatomy
knowledge) — they are not derived from our own queries against
`male-cns:v1.0`. If any of these facts were to feed into classification
code (e.g. a new rule in `io_classification_rules.md`), it should first
be verified against a specific source publication — for now it only
serves to provide context, and isn't encoded in any rule.
