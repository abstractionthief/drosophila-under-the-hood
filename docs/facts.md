# Facts & figures

A running collection of specific, sourced numbers and comparisons that came
up while exploring this project — the kind of thing worth quoting directly
(in a post, a conversation, a slide) without re-deriving or re-searching it.
Each entry says where the number comes from. Distinct from
`domain_reference.md` (general biology background) and `project_overview.md`
(what *we* built) — this file is external facts about the field.

---

## Connectome completeness: MaleCNS vs. other datasets

The comparison below uses **synaptic attachment completeness**: the
percentage of **automatically detected synaptic sites** attached to
proofread neuron segments, tracked separately for presynaptic (output)
and postsynaptic (input) sites. The denominator is detected sites, not
all synapses that existed in the animal. This measures attachment to
reconstructed neurons, not whether every site or connection was manually
verified.

| Dataset | Presynaptic completeness | Postsynaptic completeness |
|---|---|---|
| **MaleCNS** (this project's data) | **94%** | **42%** |
| FlyWire (adult female whole brain) | 93.7% | 44.7% |

Hemibrain isn't in this table: its commonly-cited "~36%" figure is
**neuropil volume coverage** (36% of all synaptic neuropils by volume,
54% of central-brain neuropils specifically), not synaptic completeness,
so it isn't comparable to the two rows above - and a directly comparable
hemibrain synaptic-completeness figure wasn't found. See source below.

Sources:
- [FlyEM / Hemibrain — Janelia Research Campus](https://www.janelia.org/project-team/flyem/hemibrain)

**Why the two rates differ:** the FlyWire paper attributes its lower
postsynaptic attachment rate to incomplete proofreading and reattachment
of thin neuronal branches ("twigs"), which contain most postsynaptic sites.
It also reports variation between neuropils and remaining synapse-detection
errors. MaleCNS shows a similar gap in the headline rates, but that does
not establish a universal ratio or a quality ranking between datasets.
These figures describe substantial reconstructions with remaining gaps;
they do not establish complete verification of the wiring.

**Other MaleCNS headline numbers** (Berg et al. 2026): 166,700
proofread/annotated neurons (close to, but not identical to, our own
`status == "Traced"` count of 165,122; the difference in counting scope
is not resolved here), 125 million synapses, 11,710 distinct
neuron types, ~44 person-years of proofreading effort.

**Do not confuse this with our own `io_role` classification coverage**
(~79% of the raw census got a confident input/processing/output label, ~21%
`unknown`) - that's a different measurement. An `unknown` role reflects
missing or unresolved metadata under our classification rules. It does
not by itself measure the completeness or accuracy of that neuron's
reconstructed connectivity, which must be assessed separately.

Sources:
- [Sexual dimorphism in the complete connectome of the Drosophila male central nervous system — Cell (2026)](https://www.cell.com/cell/fulltext/S0092-8674(26)00942-6)
- [Male CNS Connectome — official project site, Janelia Research Campus](https://male-cns.janelia.org/)
- [Neuronal wiring diagram of an adult brain — Nature (2024, FlyWire)](https://www.nature.com/articles/s41586-024-07558-y)

---

## Individual variability: how much does one fly's wiring generalize to "flies in general"?

A separate question from completeness above (which measures how well *one*
specimen was traced): connectomes are reconstructions of a single physical
individual, so how much does any one fly's map generalize? This has actually
been studied by comparing overlapping regions of two independent
reconstructions from different flies: the partial hemibrain connectome
and the whole-brain FlyWire connectome.

- **About one-third of cell types proposed from the hemibrain could not be
  reliably re-identified in FlyWire.** The other ~two-thirds matched
  reliably across the two different individuals.
- This led researchers to a deliberately *inter-individual* operational
  definition of "cell type": a group of cells that are each **more similar
  to cells in a different brain than to any other cell in their own
  brain**. Cell type, in other words, is defined by matching across
  individuals, not by clustering within one.
- **Connection strength predicts conservation**: connections stronger than
  ~10 unitary synapses, or providing >1% of a target cell's total input,
  are highly conserved between individuals. Weaker connections vary much
  more from fly to fly.
- **Concrete example of real variability**: Kenyon cells (the mushroom
  body's learning/memory neurons) are **about 30% more numerous per
  hemisphere in FlyWire than in hemibrain** (2,597 right / 2,580 left in
  FlyWire vs. 1,917 in hemibrain) - well above the ~5±12% average
  cross-individual variation seen for cell counts generally. Despite that,
  the study found evidence for functional homeostasis within the
  **mushroom-body circuit**: KCg-m Kenyon cells received proportionally
  less excitatory and inhibitory input, preserving a similar
  excitation/inhibition ratio. This is a circuit-specific inference from
  connectivity, not a measurement of whole-brain physiological balance.

**So, two genuinely different axes, easy to conflate:**
1. *Attachment completeness* (94%/42% for MaleCNS) = how many detected
   synaptic sites were attached to proofread neuron segments. It does not
   measure recovery of all of **one individual's** actual synapses.
2. *Cross-individual conservation* (~2/3 of cell types, connections
   >10 synapses) = how much **one individual's wiring generalizes** to
   flies as a class. A biological variability question - real, documented,
   and distinct from #1.

Source:
- [Whole-brain annotation and multi-connectome cell typing of Drosophila — Nature (2024)](https://www.nature.com/articles/s41586-024-07686-5)
