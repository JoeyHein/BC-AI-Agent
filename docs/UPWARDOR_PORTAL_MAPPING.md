# Upwardor Portal - Quote Builder Mapping Guide

## Portal Overview

**URL**: http://195.35.8.196:8100/
**Purpose**: Door configurator / Quote builder
**Backend API**: http://195.35.8.196:6100/

## Quote Creation Flow

### Step 1: Choose Quote Type
**3 Options:**
1. **Build A Door** ← Most common for quote requests
2. **Operators, Crownwall And Accessories** ← Add-ons
3. **Bulk Parts & Hardware** ← Component orders

---

## "Build A Door" Form Fields

### Required Fields (marked with *)

| Field Name | Type | Example Values | Notes |
|------------|------|----------------|-------|
| **Door Type*** | Dropdown | Residential, Commercial | Determines available series |
| **Door Series*** | Dropdown | TX 450, KANATA, AL976, PANORAMA | Product line |
| **Number Of Panel*** | Number Input | 1, 2, 3, etc. | Quantity of doors |
| **Panel Width*** | Dropdown | 90, 96, 108, etc. | Width in inches |
| **Panel Length/Height*** | Dropdown | D7'6, D8'0, D9'0, etc. | Height (D = Door height format) |
| **Stamp Pattern*** | Dropdown | SKML, UDC GROOVE, RIBBED, FLUSH | Door panel design |
| **Color*** | Dropdown | WHITE, ALMOND, SANDSTONE, BRONZE, etc. | Finish color |

### Optional Components

#### Panels Configuration
| Field | Type | Options | Notes |
|-------|------|---------|-------|
| **Panels Only (Bulk)** | Radio | Yes / No | Just panels vs full door package |
| **Single End Caps** | Radio | Yes / No | End caps for panels |
| **Double End Caps** | Radio | Yes / No | Both end caps |

#### Window Configuration
| Field | Type | Options | Notes |
|-------|------|---------|-------|
| **Window** | Dropdown | Select window, (various window types) | Optional window sections |

#### Track System
| Field | Type | Options | Notes |
|-------|------|---------|-------|
| **Tracks** | Radio | Yes / No | Include track hardware |
| **Track Type** | Dropdown | STANDARD LIFT BRACKET MOUNT, etc. | Type of track mounting |
| **Track Size** | Dropdown | 2 INCH TRACK, etc. | Track gauge |
| **Track Measurement** | Dropdown | 15, 18, etc. | Track length/size |
| **Track Material** | Dropdown | BRACKET TO WOOD, etc. | Mounting type |
| **Special Track Request** | Checkbox | Yes / No | Custom track requirements |

#### Hardware Components
| Component | Type | Default | Notes |
|-----------|------|---------|-------|
| **Shafts** | Radio | Yes / No | Torsion shaft |
| **Springs** | Radio | Yes / No | Torsion springs |
| **Struts** | Radio | Yes / No | Panel reinforcement |
| **Hardware Kits** | Radio | Yes / No | Complete hardware package |
| **Astragal And Bottom Retainer** | Radio | Yes / No | Bottom seal |
| **Base Struts Quantity** | Number | 1 | Required struts |
| **Extra Struts Quantity** | Number | 0 | Additional struts |
| **Weather Stripping** | Radio | Yes / No | Seal kit |
| **Decorative Hardware Parts** | Radio | Yes / No | Handles, hinges, etc. |

---

## Door Series Details

### TX 450 (Most Common)
**Full Name**: TX450 Series - Pre-configured packages
**Characteristics**:
- Has 28 pre-configured door packages (TX450-WWHH-03 format)
- Can also be built component-by-component
- Residential and Commercial options
- Standard sizes readily available

**Example SKU Format**: TX450-WWHH-03
- **WW** = Width code
- **HH** = Height code
- **03** = Configuration variant

### KANATA
**Characteristics**:
- Component-level builds only
- No pre-configured packages
- Custom configurations

### AL976
**Characteristics**:
- Aluminum construction
- Component builds
- Different hardware requirements

### PANORAMA
**Characteristics**:
- Full-view glass doors
- Specialty hardware
- Custom builds only

---

## Mapping Email Requests to Portal Fields

### Example Email → Portal Mapping

**Email Content**:
> "Need quote for 2 overhead doors, 9x7 white, standard residential"

**Portal Mapping**:
```
Door Type: Residential
Door Series: TX 450 (most common)
Number Of Panel: 2
Panel Width: 108 (9 feet = 108 inches)
Panel Height: D7'0 (7 feet)
Stamp Pattern: (Ask customer - default: RIBBED or FLUSH)
Color: WHITE
Panels Only: No (assume full door package)
Tracks: Yes (standard residential)
Shafts: Yes
Springs: Yes
Hardware Kits: Yes
```

**Email Content**:
> "Commercial door, 16x14, insulated, with windows"

**Portal Mapping**:
```
Door Type: Commercial
Door Series: TX 450 or KANATA
Number Of Panel: 1
Panel Width: 192 (16 feet = 192 inches)
Panel Height: D14'0 (14 feet)
Stamp Pattern: (Ask customer)
Color: (Ask customer - default: WHITE)
Window: (Specify window type - need details)
Panels Only: No
All hardware: Yes (commercial package)
```

---

## AI Parsing Strategy

### Information Extraction Priority

**1. Essential Info (MUST have)**:
- ✅ Door quantity
- ✅ Door size (width x height)
- ✅ Door type (residential/commercial)

**2. Important Info (Should have)**:
- ⚠️ Color
- ⚠️ Stamp pattern/style
- ⚠️ Window requirements

**3. Nice-to-Have (Can default)**:
- 💡 Track type (default: standard)
- 💡 Hardware (default: yes, full package)
- 💡 Weather stripping (default: yes)
- 💡 Struts quantity (default: 1)

**4. Missing Info Handling**:
```json
{
  "status": "needs_clarification",
  "missing_fields": ["color", "stamp_pattern"],
  "default_suggestions": {
    "color": "WHITE",
    "stamp_pattern": "RIBBED",
    "door_series": "TX 450"
  }
}
```

---

## Quote Generation Workflow

### Phase 1: Email Parsing (Current)
```
Email → AI Parse → Extract fields → Store in DB
```

### Phase 2: Portal Mapping (Next)
```
Parsed Data → Map to Portal Fields → Validate → Show to user for review
```

### Phase 3: Quote Generation (Future)
```
Approved Fields → Call Upwardor API → Generate Quote → Store Quote ID
```

Or if direct BC integration:
```
Approved Fields → Map to BC Quote Format → Call BC API → Create Quote
```

---

## Validation Rules

### Size Validation
- **Width**: Must be valid panel width (90, 96, 108, 120, 144, 192, etc.)
- **Height**: Must be in format like D7'0, D7'6, D8'0, D9'0, D10'0, etc.
- **Common residential**: 8x7, 9x7, 16x7, 16x8
- **Common commercial**: 10x10, 12x12, 14x14, 16x14, 20x14

### Component Dependencies
```
If Panels Only = Yes:
  → Tracks = No
  → Hardware Kits = No
  → Shafts = No
  → Springs = No

If Tracks = Yes:
  → Must specify track type
  → Must specify track size

If Struts = Yes:
  → Must specify base quantity
  → Can specify extra quantity
```

### Business Rules
- Residential doors typically ≤ 18 feet wide
- Commercial doors can be up to 24+ feet wide
- Heights typically in 6" increments (7'0, 7'6, 8'0, etc.)
- Window sections reduce R-value (insulation)

---

## API Exploration Strategy

Since we can't directly authenticate to the Upwardor API via curl, here's what we can do:

### Option 1: Browser DevTools Inspection
**You do this:**
1. Open portal in browser (logged in)
2. Open DevTools (F12)
3. Go to Network tab
4. Click "Generate Quote"
5. Copy the request as cURL
6. Give me the cURL command
7. I'll analyze the API structure

### Option 2: BC API Direct Integration
**We already have:**
- BC API credentials ✅
- BC API access ✅
- 888 quotes to learn from ✅
- Component catalog ✅

**We can:**
- Skip the Upwardor portal
- Generate quotes directly in BC
- Use Upwardor portal for validation only

### Option 3: Hybrid Approach (Recommended)
**Use Upwardor as:**
- Reference for correct configurations
- Validation tool
- Part number lookup

**Use BC API for:**
- Actual quote creation
- Data retrieval
- Integration

---

## Next Steps

### 1. Complete Email → Portal Field Mapping
- [x] Documented portal structure
- [ ] Create mapping function in code
- [ ] Add validation rules
- [ ] Handle missing fields gracefully

### 2. Build Quote Preview UI
- [ ] Show parsed fields in portal format
- [ ] Let user edit/correct before submission
- [ ] Validate against portal rules
- [ ] Flag missing/ambiguous fields

### 3. Integration Decision
**Choose one:**
- **A**: Automate Upwardor portal (requires browser automation)
- **B**: Use BC API directly (we already have access)
- **C**: Hybrid (parse via Upwardor, submit via BC API)

**Recommendation**: Option B (BC API direct) is fastest and most reliable

---

## Questions to Answer

**For better AI parsing:**

1. **Default Door Series**: When email doesn't specify, what's the default?
   - Residential → TX 450?
   - Commercial → ?

2. **Common Stamp Patterns**: What are the most common?
   - RIBBED?
   - FLUSH?
   - UDC GROOVE?

3. **Window Types**: How do customers usually specify windows?
   - "with windows" → what type?
   - Default window configuration?

4. **Track Requirements**:
   - Residential always gets standard lift?
   - Commercial always gets low headroom?

5. **Color Defaults**:
   - Residential → WHITE?
   - Commercial → ?

---

## Testing Strategy

### Test Cases

**Test 1: Simple Residential**
```
Input: "2 doors, 9x7, white"
Expected Output:
- Door Type: Residential
- Series: TX 450
- Quantity: 2
- Size: 108" x 84" (D7'0)
- Color: WHITE
- Full hardware package
```

**Test 2: Commercial with Windows**
```
Input: "Commercial door 16x12 with windows, insulated"
Expected Output:
- Door Type: Commercial
- Series: TX 450 or KANATA
- Quantity: 1
- Size: 192" x 144" (D12'0)
- Windows: (need clarification on type)
- Full hardware package
```

**Test 3: Panels Only**
```
Input: "Need replacement panels, 2 panels, 8 foot wide"
Expected Output:
- Panels Only: Yes
- Quantity: 2
- Width: 96" (8 feet)
- Height: (need clarification)
- No hardware included
```

---

## Portal vs BC API Comparison

| Feature | Upwardor Portal | BC API Direct |
|---------|-----------------|---------------|
| **Authentication** | Session-based (browser) | OAuth client credentials |
| **Access** | Manual login required | Automated API calls |
| **Automation** | Difficult (needs browser automation) | Easy (REST API) |
| **Data Format** | Web forms | JSON |
| **We Have Access** | ✅ Yes (manually) | ✅ Yes (automated) |
| **Validation** | Built-in form validation | We implement rules |
| **Part Numbers** | Auto-generated | We must know part numbers |
| **Quote Creation** | Click "Generate Quote" | POST to /quotes endpoint |
| **Reliability** | UI can change | API is stable |

**Conclusion**: BC API direct integration is more reliable and automatable

---

## Summary

The Upwardor portal gives us:
- ✅ **Visual reference** for how quotes should be structured
- ✅ **Field definitions** and requirements
- ✅ **Validation rules** for configurations
- ✅ **Part number patterns** to understand

We should use it as:
- 📋 **Reference guide** for our AI to learn from
- ✅ **Validation tool** to verify our outputs
- 🎓 **Training data** for understanding valid configurations

But for actual integration:
- 🚀 **Use BC API directly** (faster, more reliable, already have access)
- 💾 **Store portal logic** in our code (validation rules, defaults, etc.)
- 🔄 **Sync part numbers** from BC API periodically

---

## Action Items

**Immediate:**
1. You explore the portal and tell me:
   - Default door series for residential vs commercial
   - Most common stamp patterns
   - Most common colors
   - How window types are selected

**Next:**
2. I'll create the mapping logic in our AI system
3. Build quote preview UI showing portal-formatted data
4. Add validation based on portal rules

**Future:**
3. Decide: Automate portal OR use BC API directly
4. Implement quote generation
5. Test with real email examples

Let me know what defaults you typically use, and I'll encode that logic into our system!
