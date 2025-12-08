const axios = require('axios');

// ============================================================================
// CONFIGURATION & CONSTANTS
// ============================================================================

const COMPOSIO_API_KEY = process.env.COMPOSIO_API_KEY;
const TELNYX_API_KEY = process.env.TELNYX_API_KEY;
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const ELEVENLABS_API_KEY = process.env.ELEVENLABS_API_KEY;

// In-memory call state storage (resets on server restart)
const callStates = new Map();

// Business Constants
const HOME_ZIP = '81039';
const PUEBLO_ZIPS = ['81001', '81003', '81004', '81005', '81006', '81007', '81008', '81009', '81010', '81011', '81012', '81019', '81020', '81021', '81022', '81023', '81025'];
const VALLEY_ZIPS = ['81020', '81021', '81022', '81024', '81027', '81030', '81041', '81043', '81050', '81054', '81055', '81059', '81062', '81063', '81071', '81073', '81082', '81089', '81090', '81091'];

const EXCLUDED_APPLIANCES = ['microwave', 'toaster', 'coffee maker', 'blender', 'mixer', 'air fryer', 'slow cooker', 'pressure cooker', 'rice cooker'];

const APPLIANCE_MENU = {
  '1': 'refrigerator',
  '2': 'oven or range',
  '3': 'dishwasher',
  '4': 'washing machine',
  '5': 'dryer',
  '6': 'other large appliance'
};

// December 2, 2025 was a TUESDAY and was a Pueblo day
const PUEBLO_REFERENCE_DATE = new Date('2025-12-02T00:00:00-07:00');

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function determineServiceZone(zip) {
  if (zip === HOME_ZIP) return 'home';
  if (PUEBLO_ZIPS.includes(zip)) return 'pueblo';
  if (VALLEY_ZIPS.includes(zip)) return 'valley';
  return null;
}

function isPuebloDay(date) {
  const daysSinceReference = Math.floor((date - PUEBLO_REFERENCE_DATE) / (1000 * 60 * 60 * 24));
  return daysSinceReference % 2 === 0;
}

function getAvailableTimeSlots(zone) {
  if (zone === 'home') {
    return ['9:00 AM', '4:00 PM'];
  } else {
    return ['9:00 AM', '11:00 AM', '1:00 PM', '3:00 PM'];
  }
}

function getNextFiveAvailableDates(zone) {
  const dates = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  let checkDate = new Date(today);
  checkDate.setDate(checkDate.getDate() + 1); // Start from tomorrow

  while (dates.length < 5) {
    const dayOfWeek = checkDate.getDay();

    // Skip weekends
    if (dayOfWeek === 0 || dayOfWeek === 6) {
      checkDate.setDate(checkDate.getDate() + 1);
      continue;
    }

    // For home zone, any weekday works
    if (zone === 'home') {
      dates.push(new Date(checkDate));
      checkDate.setDate(checkDate.getDate() + 1);
      continue;
    }

    // For Pueblo and Valley zones, check alternating days
    const isPueblo = isPuebloDay(checkDate);

    if ((zone === 'pueblo' && isPueblo) || (zone === 'valley' && !isPueblo)) {
      dates.push(new Date(checkDate));
    }

    checkDate.setDate(checkDate.getDate() + 1);
  }

  return dates;
}

function formatDateForSpeech(date) {
  const options = { weekday: 'long', month: 'long', day: 'numeric' };
  return date.toLocaleDateString('en-US', options);
}

function formatTimeForCalendar(date, timeSlot) {
  const [time, period] = timeSlot.split(' ');
  let [hours, minutes] = time.split(':').map(Number);

  if (period === 'PM' && hours !== 12) hours += 12;
  if (period === 'AM' && hours === 12) hours = 0;

  const startTime = new Date(date);
  startTime.setHours(hours, minutes || 0, 0, 0);

  const endTime = new Date(startTime);
  endTime.setHours(endTime.getHours() + 2);

  return { startTime, endTime };
}

async function checkCalendarConflicts(startTime, endTime) {
  try {
    const response = await axios.post(
      'https://backend.composio.dev/api/v1/actions/GOOGLECALENDAR_LIST_EVENTS/execute',
      {
        input: {
          timeMin: startTime.toISOString(),
          timeMax: endTime.toISOString(),
          singleEvents: true
        },
        connectedAccountId: process.env.GOOGLE_CALENDAR_ACCOUNT_ID
      },
      {
        headers: {
          'X-API-Key': COMPOSIO_API_KEY,
          'Content-Type': 'application/json'
        }
      }
    );

    const events = response.data?.data?.items || [];
    return events.length > 0;
  } catch (error) {
    console.error('Calendar check error:', error.message);
    return false; // Assume no conflict if check fails
  }
}

async function createCalendarEvent(customerName, phone, appliance, startTime, endTime, zip) {
  try {
    const response = await axios.post(
      'https://backend.composio.dev/api/v1/actions/GOOGLECALENDAR_CREATE_EVENT/execute',
      {
        input: {
          summary: `Appliance Repair - ${customerName}`,
          description: `Customer: ${customerName}\nPhone: ${phone}\nAppliance: ${appliance}\nZIP: ${zip}`,
          start: {
            dateTime: startTime.toISOString(),
            timeZone: 'America/Denver'
          },
          end: {
            dateTime: endTime.toISOString(),
            timeZone: 'America/Denver'
          }
        },
        connectedAccountId: process.env.GOOGLE_CALENDAR_ACCOUNT_ID
      },
      {
        headers: {
          'X-API-Key': COMPOSIO_API_KEY,
          'Content-Type': 'application/json'
        }
      }
    );

    return response.data?.data || null;
  } catch (error) {
    console.error('Calendar creation error:', error.message);
    return null;
  }
}
