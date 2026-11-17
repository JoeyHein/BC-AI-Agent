import assert from 'node:assert/strict'
import test from 'node:test'
import { quoteCardSubtitle, quoteCardTitle, quoteTagName } from './quoteTitle.js'

test('job name is the card title and an empty description is not shown', () => {
  const quote = {
    name: 'Lot 14 — Front Garage',
    description: '',
    bc_quote_number: 'SQ-003428',
    config_data: { poNumber: 'PO-1' },
  }
  assert.equal(quoteCardTitle(quote), 'Lot 14 — Front Garage')
  assert.equal(quoteCardSubtitle(quote), '')
})

test('display_title from the list API wins', () => {
  const quote = { name: '', description: 'notes', display_title: 'Smith Residence' }
  assert.equal(quoteCardTitle(quote), 'Smith Residence')
})

test('blank name falls back to description, then PO, then the SQ number', () => {
  assert.equal(quoteCardTitle({
    name: '  ',
    description: 'Side entrance',
    bc_quote_number: 'SQ-003430',
  }), 'Side entrance')
  assert.equal(quoteCardSubtitle({
    name: '',
    description: 'Side entrance',
    bc_quote_number: 'SQ-003430',
  }), '')
  assert.equal(quoteCardTitle({
    name: null,
    description: null,
    config_data: { poNumber: 'PO-4491' },
    bc_quote_number: 'SQ-003430',
  }), 'PO-4491')
  assert.equal(quoteCardTitle({
    name: null,
    description: null,
    bc_quote_number: 'SQ-003428',
  }), 'SQ-003428')
  assert.equal(quoteCardTitle({}), 'Quote')
})

test('a tag saved only in config_data is the title and the editable name', () => {
  const quote = {
    name: null,
    description: null,
    config_data: { tagName: 'Smith Residence' },
    bc_quote_number: 'SQ-003431',
  }
  assert.equal(quoteTagName(quote), 'Smith Residence')
  assert.equal(quoteCardTitle(quote), 'Smith Residence')
})
