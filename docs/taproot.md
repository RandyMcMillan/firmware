# Taproot

**COLDCARD<sup>&reg;</sup>** Mk4 experimental `EDGE` versions will
support Schnorr signatures ([BIP-0340](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki)), 
Taproot ([BIP-0341](https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki)) 
and very limited Tapscript ([BIP-0342](https://github.com/bitcoin/bips/blob/master/bip-0342.mediawiki)) support.
Tapscript support will get more versatile with future iterations.

## Output script (a.k.a address) generation

If the spending conditions do not require a script path, the output key MUST commit to an unspendable script path. 
`Q = P + int(hashTapTweak(bytes(P)))G` a.k.a internal key MUST be tweaked by `TapTweak` tagged hash of itself. If 
the spending conditions require script path, internal key MUST be tweaked by `TapTweak` tagged hash of tree merkle root.

Addresses in `Address Explorer` for `p2tr` are generated with above-mentioned methods. Outputs `scriptPubkeys` in PSBT
MUST be generated with above-mentoned methods to be considered change.

## Allowed descriptors

1. Single signature wallet without script path: `tr(key)`
2. Tapscript multisig with internal key and one sortedmulti multisig script: `tr(internal_key, sortedmulti_a(MofN))`

## Provably unspendable internal key

There are few methods to provide/generate provably unspendable internal key, if users wish to only use script path
for multisig.

1. use provably unspendable internal key H from [BIP-0341](https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki#constructing-and-spending-taproot-outputs). This way is leaking the information that key path spending is not possible and therefore not recommended privacy-wise.
    
    `tr(50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0, sortedmulti_a(MofN))`

2. use COLDCARD specific placeholder `@` to let HWW pick a fresh integer r in the range 0...n-1 uniformly at random and use `H + rG` as internal key. COLDCARD will not store r and therefore user is not able to prove to other party how the key was generated and whether it is actually unspendable.
    
    `tr(r=@, sortedmulti_a(MofN))`

3. pick a fresh integer r in the range 0...n-1 uniformly at random yourself and provide that in the descriptor. COLDCARD generates internal key with `H + rG`. It is possible to prove to other party that this internal key does not have a known discrete logarithm with respect to G by revealing r to a verifier who can then reconstruct how the internal key was created.
    
    `tr(r=77ec0c0fdb9733e6a3c753b1374c4a465cba80dff52fc196972640a26dd08b76, sortedmulti_a(MofN))`


## Limitations

### Tapscript Limitations

In current version only `TREE` of depth 0 is allowed. Meaning that only one leaf script is allowed 
and tagged hash of this single leaf script is also a merkle root. Only allowed script (for now) is `sortedmulti_a`.
Taproot multisig currently has artificial limit of max 32 signers (M=N=32).

If Coldcard can sign by both key path and script path - key path has precedence.

### PSBT Requirements

PSBT provider MUST provide following Taproot specific input fields in PSBT:
1. `PSBT_IN_TAP_BIP32_DERIVATION` with all the necessary keys with their leaf hashes and derivation (including XFP). Internal key has to be specified here with empty leaf hashes.
2. `PSBT_IN_TAP_INTERNAL_KEY` MUST match internal key provided in `PSBT_IN_TAP_BIP32_DERIVATION`
3. `PSBT_IN_TAP_MERKLE_ROOT` MUST be empty if there is no script path. Otherwise it MUST match what Coldcard can calculate from registered descriptor.
4. `PSBT_IN_TAP_LEAF_SCRIPT` MUST be specified if there is a script path. Currently MUST be of length 1 (only one script allowed)

PSBT provider MUST provide following Taproot specific output fields in PSBT:
1. `PSBT_OUT_TAP_BIP32_DERIVATION` with all the necessary keys with their leaf hashes and derivation (including XFP). Internal key has to be specified here with empty leaf hashes.
2. `PSBT_OUT_TAP_INTERNAL_KEY` must match internal key provided in `PSBT_OUT_TAP_BIP32_DERIVATION`
3. `PSBT_OUT_TAP_TREE` with depth, leaf version and script defined. Currently only one script is allowed.
