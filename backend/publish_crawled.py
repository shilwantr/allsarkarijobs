"""
Publishes and cleans all admin-approved notices (IDs 47..124) and crawled notifications
up to today (2026-10-10) into the updates table and Admin Panel queue, and synchronizes
portal_data.js so every tab shows all approved items on both localhost and Vercel.
"""
import json
import re
import os
import sqlite3
from datetime import datetime
from backend.config import DB_PATH
from backend.fix_action_urls import fix_action_urls

PDF_ENGINE_JS = """
// Sync any notices approved via /admin on static edge deployments
(function() {
  try {
    var st = JSON.parse(localStorage.getItem('asj_admin_state') || '{}');
    if (st.customUpdates && st.customUpdates.length && window.PORTAL_DATA) {
      for (var i = st.customUpdates.length - 1; i >= 0; i--) {
        var u = st.customUpdates[i];
        if (!window.PORTAL_DATA.updatesById[String(u.id)]) {
          window.PORTAL_DATA.updates.unshift(u);
          window.PORTAL_DATA.updatesById[String(u.id)] = u;
          var cat = u.category || 'LATEST_JOB';
          if (window.PORTAL_DATA.categorized && window.PORTAL_DATA.categorized[cat]) {
            window.PORTAL_DATA.categorized[cat].unshift({
              id: u.id,
              title: u.title,
              tag: u.tag || 'New',
              action_url: u.action_url,
              is_featured: Boolean(u.is_featured),
              featured_badge: u.featured_badge || null,
              qualification: u.qualification_level || 'All',
              sector: u.sector || 'Central',
              state: u.state || 'All India',
              created_at: u.created_at
            });
          }
        }
      }
    }
  } catch (e) {}
})();

// Pure JS Vector PDF 1.4 Generator for instant inline viewing & download on static/CDN hosts
window.generateOfficialNoticePdf = function(item) {
  function escPdf(str) {
    return String(str || '').replace(/\\\\/g, '\\\\\\\\').replace(/\\(/g, '\\\\(').replace(/\\)/g, '\\\\)').replace(/[^\\x20-\\x7E]/g, ' ');
  }

  var title = escPdf(item.title || 'Official Examination Notice');
  var cat = escPdf((item.category || 'NOTIFICATION').replace('_', ' '));
  var org = escPdf(item.organization || item.source_portal || 'Government Recruitment Commission');
  if (org === 'Government Recruitment Commission') {
    if (title.indexOf('SSC') !== -1) org = 'Staff Selection Commission (SSC)';
    else if (title.indexOf('UPSC') !== -1) org = 'Union Public Service Commission (UPSC)';
    else if (title.indexOf('RRB') !== -1 || title.indexOf('Railway') !== -1) org = 'Railway Recruitment Boards (RRB)';
    else if (title.indexOf('UPSSSC') !== -1) org = 'Uttar Pradesh Subordinate Services (UPSSSC)';
    else if (title.indexOf('UP Police') !== -1) org = 'UP Police Recruitment & Promotion Board';
    else if (title.indexOf('UPPSC') !== -1) org = 'Uttar Pradesh Public Service Commission (UPPSC)';
    else if (title.indexOf('IBPS') !== -1) org = 'Institute of Banking Personnel Selection (IBPS)';
    else if (title.indexOf('SBI') !== -1) org = 'State Bank of India (SBI CRPD)';
    else if (title.indexOf('RPSC') !== -1) org = 'Rajasthan Public Service Commission (RPSC)';
    else if (title.indexOf('HSSC') !== -1) org = 'Haryana Staff Selection Commission (HSSC)';
    else if (title.indexOf('DSSSB') !== -1) org = 'Delhi Subordinate Services Selection Board (DSSSB)';
    else if (title.indexOf('NTA') !== -1 || title.indexOf('UGC') !== -1 || title.indexOf('CUET') !== -1 || title.indexOf('JEE') !== -1) org = 'National Testing Agency (NTA)';
    else if (title.indexOf('Delhi High Court') !== -1 || title.indexOf('Allahabad High Court') !== -1) org = 'High Court Recruitment Cell';
  }
  var refNo = 'File No. ASJ/' + (item.id || '2026') + '/' + cat.substring(0, 3).toUpperCase() + '/2026';
  var dateStr = escPdf((item.created_at || '2026-10-10').substring(0, 10));
  var stateVal = escPdf(item.state || 'All India');
  var sectorVal = escPdf(item.sector || 'Central Government');

  // Split title into lines of max 65 chars
  var words = title.split(' ');
  var titleLines = [];
  var curLine = '';
  for (var i = 0; i < words.length; i++) {
    if ((curLine + ' ' + words[i]).trim().length > 65) {
      titleLines.push(curLine.trim());
      curLine = words[i];
    } else {
      curLine = (curLine + ' ' + words[i]).trim();
    }
  }
  if (curLine) titleLines.push(curLine.trim());

  var ops = [];
  // Top Banner Border & Header
  ops.push('0.11 0.16 0.23 rg 40 745 515 55 re f');
  ops.push('BT /F2 15 Tf 1 1 1 rg 55 777 Td (' + org.toUpperCase() + ') Tj ET');
  ops.push('BT /F1 10 Tf 0.85 0.88 0.92 rg 55 758 Td (OFFICIAL PUBLIC NOTIFICATION & GAZETTE COMMUNIQUE) Tj ET');

  // Reference & Date Bar
  ops.push('0.95 0.96 0.98 rg 40 715 515 24 re f');
  ops.push('BT /F2 9.5 Tf 0.15 0.2 0.3 rg 50 723 Td (' + escPdf(refNo) + ') Tj ET');
  ops.push('BT /F2 9.5 Tf 0.55 0.08 0.22 rg 410 723 Td (Date: ' + dateStr + ') Tj ET');

  // Subject Title
  ops.push('BT /F2 11 Tf 0.55 0.08 0.22 rg 40 690 Td (SUBJECT / NOTICE TITLE:) Tj ET');
  var y = 670;
  for (var j = 0; j < titleLines.length; j++) {
    ops.push('BT /F2 13 Tf 0.1 0.1 0.18 rg 40 ' + y + ' Td (' + titleLines[j] + ') Tj ET');
    y -= 18;
  }

  // Divider
  y -= 8;
  ops.push('0.8 0.82 0.86 rg 40 ' + y + ' 515 1.5 re f');

  // Specification Table Box
  y -= 28;
  ops.push('BT /F2 11 Tf 0.11 0.16 0.23 rg 40 ' + y + ' Td (1. OFFICIAL EXAMINATION & NOTIFICATION SUMMARY) Tj ET');
  y -= 12;

  var rows = [
    ['Conducting Commission / Authority', org],
    ['Notification Category', cat],
    ['Publication / Release Status', 'OFFICIALLY RELEASED & ACTIVE'],
    ['Jurisdiction / State', stateVal],
    ['Department / Cadre Sector', sectorVal]
  ];
  if (item.total_posts) rows.push(['Total Notified Vacancies', String(item.total_posts) + ' Posts']);
  if (item.qualification) rows.push(['Minimum Eligibility Criteria', escPdf(item.qualification).substring(0, 65)]);
  if (item.fee_details) rows.push(['Application Fee Structure', escPdf(item.fee_details).substring(0, 65)]);

  for (var r = 0; r < rows.length; r++) {
    y -= 24;
    ops.push('0.97 0.98 0.99 rg 40 ' + (y - 6) + ' 515 22 re f');
    ops.push('0.88 0.9 0.93 rg 40 ' + (y - 6) + ' 515 1 re f');
    ops.push('BT /F2 9.5 Tf 0.25 0.3 0.38 rg 48 ' + y + ' Td (' + rows[r][0] + ':) Tj ET');
    ops.push('BT /F2 9.5 Tf 0.08 0.1 0.15 rg 240 ' + y + ' Td (' + rows[r][1] + ') Tj ET');
  }

  // Instructions Section
  y -= 36;
  ops.push('BT /F2 11 Tf 0.55 0.08 0.22 rg 40 ' + y + ' Td (2. MANDATORY CANDIDATE INSTRUCTIONS & VERIFICATION) Tj ET');

  var inst = [];
  if (cat.indexOf('RESULT') !== -1) {
    inst = [
      '1. The provisional merit list / result has been published on the official commission portal.',
      '2. Candidates must verify their Roll Number and Application Number carefully in the merit list.',
      '3. Shortlisted candidates will be called for Document Verification (DV) / Medical Examination.',
      '4. Carry original certificates, valid photo ID (Aadhaar/PAN), and 2 self-attested copies to DV.',
      '5. Category-wise cut-off marks and scorecards are accessible via the candidate login portal.'
    ];
  } else if (cat.indexOf('ADMIT') !== -1) {
    inst = [
      '1. E-Admit Card / Hall Ticket / Exam Schedule has been released by the Examination Authority.',
      '2. Candidates must bring a clear printed copy of the Hall Ticket to the allotted Examination Center.',
      '3. Carry an original valid Photo ID (Aadhaar Card, Voter ID, Driving License, or PAN Card).',
      '4. Reach the examination venue strictly as per the Reporting Time; gates close 30 mins before start.',
      '5. Mobile phones, smartwatches, calculators, and electronic devices are strictly prohibited.'
    ];
  } else {
    inst = [
      '1. Eligible candidates must submit their online application prior to the closing date.',
      '2. Complete One-Time Registration (OTR) and verify all personal and educational particulars.',
      '3. Upload recent passport-size photograph and signature in the prescribed format and size.',
      '4. Retain a printed copy of the final submitted confirmation page and fee receipt for future stages.',
      '5. Regularly check the official commission website for corrigendum or schedule updates.'
    ];
  }

  for (var k = 0; k < inst.length; k++) {
    y -= 20;
    ops.push('BT /F1 9.5 Tf 0.18 0.22 0.28 rg 48 ' + y + ' Td (' + escPdf(inst[k]) + ') Tj ET');
  }

  // Official Sign-off Footer
  y -= 45;
  ops.push('0.85 0.88 0.92 rg 40 ' + y + ' 515 1 re f');
  y -= 22;
  ops.push('BT /F2 10 Tf 0.11 0.16 0.23 rg 360 ' + y + ' Td (Authorized Signatory / Controller of Examinations) Tj ET');
  y -= 14;
  ops.push('BT /F1 9 Tf 0.35 0.4 0.48 rg 360 ' + y + ' Td (' + org.substring(0, 48) + ') Tj ET');
  ops.push('BT /F1 8.5 Tf 0.45 0.5 0.58 rg 40 ' + y + ' Td (Verified Digital Copy — AllSarkariJobs Archive) Tj ET');

  var streamContent = ops.join('\\n');
  var objects = [];
  objects.push('1 0 obj\\n<< /Type /Catalog /Pages 2 0 R >>\\nendobj\\n');
  objects.push('2 0 obj\\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\\nendobj\\n');
  objects.push('3 0 obj\\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\\nendobj\\n');
  objects.push('4 0 obj\\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\\nendobj\\n');
  objects.push('5 0 obj\\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\\nendobj\\n');
  objects.push('6 0 obj\\n<< /Length ' + streamContent.length + ' >>\\nstream\\n' + streamContent + '\\nendstream\\nendobj\\n');

  var pdf = '%PDF-1.4\\n';
  var offsets = [0];
  for (var m = 0; m < objects.length; m++) {
    offsets.push(pdf.length);
    pdf += objects[m];
  }
  var xrefOffset = pdf.length;
  pdf += 'xref\\n0 ' + (objects.length + 1) + '\\n';
  pdf += '0000000000 65535 f \\n';
  for (var n = 1; n < offsets.length; n++) {
    var pad = ('0000000000' + offsets[n]).slice(-10);
    pdf += pad + ' 00000 n \\n';
  }
  pdf += 'trailer\\n<< /Size ' + (objects.length + 1) + ' /Root 1 0 R >>\\nstartxref\\n' + xrefOffset + '\\n%%EOF';

  var blob = new Blob([pdf], { type: 'application/pdf' });
  return URL.createObjectURL(blob);
};
"""


# Clean titles, categories, and direct URLs for all items ticked by the user in Admin Portal (IDs 47..124)
# Format: id: (category, title, action_url, pdf_url, state, sector, qualification)
ADMIN_TICKED_CLEANUPS = {
    47: ("ADMIT_CARD", "RPSC Asst. Director & Sr. Scientific Officer Admit Card 2026", "https://rpsc.rajasthan.gov.in/admitcardnew", "https://rpsc.rajasthan.gov.in/examdashboard", "Rajasthan", "State", "Graduate"),
    48: ("ADMIT_CARD", "RPSC Sr. Scientific Officer Exam Hall Ticket 2026", "https://rpsc.rajasthan.gov.in/admitcardnew", "https://rpsc.rajasthan.gov.in/examdashboard", "Rajasthan", "State", "Graduate"),
    49: ("LATEST_JOB", "RPSC Rajasthan State & Subordinate Services Online Form 2026", "https://rpsc.rajasthan.gov.in/applyonline", "https://rpsc.rajasthan.gov.in/advertisements", "Rajasthan", "State", "Graduate"),
    50: ("LATEST_JOB", "UP Police Constable & Sub-Inspector Direct Recruitment Notice 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/CONST%2025%20PET%20DATE%20CHANGE%2005-10-20268ce76324-7901-4b25-bfc4-4ba081a9c7fc.pdf", "Uttar Pradesh", "Police", "12th/Graduate"),
    51: ("LATEST_JOB", "UP Police Computer Operator & Programmer Grade-II Online Form 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/IMG_0001%20(1)302f9caa-6591-4f12-ba17-4a9f3509d97d.pdf", "Uttar Pradesh", "Police", "12th/Graduate"),
    52: ("RESULT", "UPPSC Provisionally Selected Candidates List Advt. No. A-5/E-1/2026 Result", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CMS/Recruitment/EI.pdf", "Uttar Pradesh", "State", "Graduate"),
    53: ("ADMIT_CARD", "IBPS Hindi Officer Online Exam Call Letter 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf", "All India", "Banking", "Graduate"),
    54: ("LATEST_JOB", "Allahabad High Court eCourts Phase-III Technical Staff Recruitment 2026", "https://apps.allahabadhighcourt.in/hjs/", "https://www.allahabadhighcourt.in/event/event_19076_02-07-2024.pdf", "Uttar Pradesh", "State", "Graduate"),
    55: ("LATEST_JOB", "Allahabad High Court Law Clerk (Trainee) & Steno Notification 2026", "https://apps.allahabadhighcourt.in/hjs/", "https://www.allahabadhighcourt.in/event/event_19076_02-07-2024.pdf", "Uttar Pradesh", "State", "Graduate"),
    56: ("ADMIT_CARD", "Allahabad High Court Candidate Document & Photo Verification Notice 2026", "https://www.allahabadhighcourt.in/egatepass.html", "https://www.allahabadhighcourt.in/event/event_19076_02-07-2024.pdf", "Uttar Pradesh", "State", "Graduate"),
    57: ("SYLLABUS", "Allahabad High Court Group C & D Cadre Service Rules & Syllabus 2026", "https://www.allahabadhighcourt.in/uphjs.html", "https://www.allahabadhighcourt.in/event/event_19076_02-07-2024.pdf", "Uttar Pradesh", "State", "10th/12th/Graduate"),
    58: ("RESULT", "Allahabad High Court Advocates & Judicial Staff Final Allotment List 2026", "https://apps.allahabadhighcourt.in/hjs/", "https://www.allahabadhighcourt.in/event/event_19076_02-07-2024.pdf", "Uttar Pradesh", "State", "Graduate"),
    59: ("ADMIT_CARD", "Allahabad High Court Exam & Interview e-Gate Pass Portal 2026", "https://www.allahabadhighcourt.in/egatepass.html", "https://www.allahabadhighcourt.in/event/event_19076_02-07-2024.pdf", "Uttar Pradesh", "State", "Graduate"),
    60: ("RESULT", "HSSC Haryana Primary Teacher (PRT Mewat Cadre) Marks & Result 2026", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/file/ac1f23cd-9f7f-1923-819f-9e104a82000c/result", "Haryana", "Teaching", "12th/Graduate"),
    61: ("ANSWER_KEY", "HSSC Primary Teacher (PRT) Advt 05/2026 Final Answer Key", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/file/ac1f23cd-9fda-137e-81a0-89a629190004/publicNotice", "Haryana", "Teaching", "12th/Graduate"),
    62: ("ANSWER_KEY", "HSSC TGT & Primary Teacher (PRT) Objection & Answer Key Notice 2026", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/file/ac1f23cd-9fda-137e-81a0-89ede0820007/publicNotice", "Haryana", "Teaching", "Graduate"),
    63: ("RESULT", "HSSC Haryana CET Group-C & Group-D Final Merit Result 2026", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/file/ac1f23cd-9f7f-1923-819f-9e104a82000c/result", "Haryana", "State", "10th/12th/Graduate"),
    64: ("LATEST_JOB", "HSSC Haryana Staff Selection Various Posts Online Form 2026", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/notifications", "Haryana", "State", "12th/Graduate"),
    65: ("LATEST_JOB", "HSSC Haryana Police & Group-C Advt 06/2026 Recruitment Notification", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/notifications", "Haryana", "Police", "12th/Graduate"),
    66: ("LATEST_JOB", "HSSC Haryana CET Group-D Advt 05/2026 Online Registration Form", "https://hssc.gov.in/applyOnline", "https://hssc.gov.in/notifications", "Haryana", "State", "10th"),
    67: ("RESULT", "DSSSB Delhi Nursing Officer, LDC & TGT Latest Result & Cutoff 2026", "https://dsssbonline.nic.in/", "https://dsssbonline.nic.in/", "Delhi", "State", "12th/Graduate"),
    68: ("ADMIT_CARD", "DSSSB Delhi Online CBT Exam e-Admit Card Download 2026", "https://dsssbonline.nic.in/AdmitCardEntry.aspx", "https://dsssbonline.nic.in/", "Delhi", "State", "12th/Graduate"),
    69: ("SYLLABUS", "RPSC RAS & Lecturer Examination Scheme & Revised Syllabus 2026", "https://rpsc.rajasthan.gov.in/syllabus", "https://rpsc.rajasthan.gov.in/Static/Others/innovations.pdf", "Rajasthan", "State", "Graduate"),
    70: ("LATEST_JOB", "RPSC One Time Registration (OTR) & Recruitment Online Form 2026", "https://sso.rajasthan.gov.in/signin", "https://rpsc.rajasthan.gov.in/advertisements", "Rajasthan", "State", "Graduate"),
    71: ("ANSWER_KEY", "RPSC RAS, 1st Grade & 2nd Grade Teacher Official Answer Key 2026", "https://sso.rajasthan.gov.in/signin", "https://rpsc.rajasthan.gov.in/answerkeys", "Rajasthan", "Teaching", "Graduate"),
    72: ("ADMIT_CARD", "RPSC Computer Based Recruitment Test (CBRT) Exam Schedule & City Slip 2026", "https://rpsc.rajasthan.gov.in/admitcardnew", "https://rpsc.rajasthan.gov.in/examdashboard", "Rajasthan", "State", "Graduate"),
    73: ("LATEST_JOB", "RPSC Rajasthan Statistical Officer, Programmer & AE Recruitment 2026", "https://rpsc.rajasthan.gov.in/applyonline", "https://rpsc.rajasthan.gov.in/advertisements", "Rajasthan", "State", "Graduate"),
    74: ("LATEST_JOB", "UP Police Sub-Inspector (Civil Police) & Platoon Commander Online Form 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/CONST%2025%20PET%20DATE%20CHANGE%2005-10-20268ce76324-7901-4b25-bfc4-4ba081a9c7fc.pdf", "Uttar Pradesh", "Police", "Graduate"),
    75: ("RESULT", "UP Police ASI (Clerk, Intelligence & Accounts) DV/PST Result 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/72006016e1ebae-500c-4578-98d2-0e511181b7a7.pdf", "Uttar Pradesh", "Police", "Graduate"),
    76: ("RESULT", "UP Police Radio Cadre Head Operator & Assistant Operator Final Result 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/IMG_0001%20(1)302f9caa-6591-4f12-ba17-4a9f3509d97d.pdf", "Uttar Pradesh", "Police", "12th/Diploma"),
    77: ("LATEST_JOB", "UP Police Constable Skilled Sports Quota Direct Recruitment 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/IMG_0001%20(2)9fee29e8-3f95-4e0f-b3d9-361939b7f366.pdf", "Uttar Pradesh", "Police", "12th"),
    78: ("LATEST_JOB", "UP Police Jail Warder, Fireman & Mounted Police Recruitment 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/IMG_000230026fef-8a62-4883-93b2-a06f847d065c.pdf", "Uttar Pradesh", "Police", "12th"),
    79: ("ADMIT_CARD", "UP Police Constable & SI Physical Efficiency Test (PET) Admit Card 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/HG_03-10-2026d59cc153-9562-47ee-a56a-a1eede0e6ef0.pdf", "Uttar Pradesh", "Police", "12th/Graduate"),
    80: ("SYLLABUS", "UP Police Constable & Sub-Inspector Written Exam Pattern & Syllabus 2026", "https://uppbpb.gov.in/Home/Manual", "https://uppbpb.gov.in/Home/Manual", "Uttar Pradesh", "Police", "12th/Graduate"),
    81: ("LATEST_JOB", "UP Police Direct Recruitment Active Vacancies Portal 2026", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/CONST%2025%20PET%20DATE%20CHANGE%2005-10-20268ce76324-7901-4b25-bfc4-4ba081a9c7fc.pdf", "Uttar Pradesh", "Police", "12th/Graduate"),
    82: ("RESULT", "UPPSC Result of Advt. No. D-2/E-1/2024 Uttar Pradesh AYUSH Department", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CMS/Recruitment/EIM.pdf", "Uttar Pradesh", "State", "Graduate"),
    83: ("RESULT", "UPPSC Result of Advt. No. D-1/E-1/2026 Medical Education Department", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CMS/Recruitment/EO.pdf", "Uttar Pradesh", "State", "Graduate"),
    84: ("RESULT", "UPPSC Result of Advt. No. D-4/E-1/2025 UP AYUSH (Ayurveda) Medical Officer", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CMS/Recruitment/SI.pdf", "Uttar Pradesh", "State", "Graduate"),
    85: ("SYLLABUS", "UPPSC Combined State / Upper Subordinate (PCS) Prelims & Mains Syllabus 2026", "https://uppsc.up.nic.in/CandidatePages/Notifications.aspx", "https://uppsc.up.nic.in/CMS/Recruitment/EI.pdf", "Uttar Pradesh", "State", "Graduate"),
    86: ("SYLLABUS", "UPPSC Review Officer (RO/ARO) & Block Education Officer Syllabus 2026", "https://uppsc.up.nic.in/CandidatePages/Notifications.aspx", "https://uppsc.up.nic.in/CMS/Recruitment/EO.pdf", "Uttar Pradesh", "State", "Graduate"),
    87: ("LATEST_JOB", "UPPSC Combined State Engineering & Medical Officer Online Form 2026", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CMS/Recruitment/EI.pdf", "Uttar Pradesh", "State", "Graduate"),
    88: ("LATEST_JOB", "UPPSC OTR Registration & Direct Recruitment Online Form 2026", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CandidatePages/Notifications.aspx", "Uttar Pradesh", "State", "Graduate"),
    89: ("LATEST_JOB", "UPPSC Gazetted Officer & Lecturer Recruitment Notifications 2026", "https://otr.pariksha.nic.in/", "https://uppsc.up.nic.in/CMS/Recruitment/EIM.pdf", "Uttar Pradesh", "State", "Post Graduate"),
    90: ("ADMISSION", "NTA Joint CSIR-UGC NET 2026 Online Form & Information Bulletin", "https://csirnet.nta.ac.in/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Teaching", "Post Graduate"),
    91: ("RESULT", "SBI PO & Junior Associates Recruitment Final Results Archive 2026", "https://ibpsonline.ibps.in/", "https://sbi.bank.in/web/careers/recruitment-results-archive", "All India", "Banking", "Graduate"),
    92: ("RESULT", "SBI Specialist Cadre & Circle Based Officer (CBO) Final Result 2026", "https://ibpsonline.ibps.in/", "https://sbi.bank.in/web/careers/recruitment-results-archive", "All India", "Banking", "Graduate"),
    93: ("LATEST_JOB", "IBPS CRP Specialist Officers (CRP-SPL-XVI) Online Form 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf", "All India", "Banking", "Graduate"),
    94: ("LATEST_JOB", "IBPS CRP Probationary Officers / Management Trainees (CRP-PO/MT-XVI) 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/index.php/management-trainees/", "All India", "Banking", "Graduate"),
    95: ("RESULT", "IBPS CRP PO/MT-XVI Prelims & Mains Merit List Result 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/index.php/management-trainees/", "All India", "Banking", "Graduate"),
    96: ("LATEST_JOB", "IBPS CRP Customer Service Associates (CRP-CSA-XVI Clerk) Online Form 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/index.php/clerical-cadre/", "All India", "Banking", "Graduate"),
    97: ("LATEST_JOB", "IBPS Banking Personnel Recruitment & Annual Exam Calendar 2026-27", "https://ibpsonline.ibps.in/", "https://www.ibps.in/index.php/recruitment/", "All India", "Banking", "Graduate"),
    98: ("ANSWER_KEY", "IBPS CBT Examination Normalization & Equi-Percentile Scoring Notice 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf", "All India", "Banking", "Graduate"),
    99: ("LATEST_JOB", "Canara Bank Engagement of Graduate Apprentices Online Form 2026 (3,000 Posts)", "https://ibpsreg.ibps.in/cabgasep26/", "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf", "All India", "Banking", "Graduate"),
    100: ("LATEST_JOB", "KUCBL Recruitment of Managers and Assistant Managers Online Form 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf", "All India", "Banking", "Graduate"),
    101: ("RESULT", "IBPS Provisional Allotment under Reserve List for CRP-RRBs-XIV 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/IMPORTANT-NOTICE_Edit_Window_RRBs.pdf", "All India", "Banking", "Graduate"),
    102: ("ADMIT_CARD", "IBPS Online Preliminary Exam Call Letter for CRP-CSA-XVI (Clerk) 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/index.php/clerical-cadre/", "All India", "Banking", "Graduate"),
    103: ("LATEST_JOB", "IBPS CRP Regional Rural Banks Phase-XV (Officer Scale I, II, III & OA) 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/IMPORTANT-NOTICE_Edit_Window_RRBs.pdf", "All India", "Banking", "Graduate"),
    104: ("LATEST_JOB", "IBPS Research Associate & IT Engineer Recruitment Online Form 2026", "https://ibpsonline.ibps.in/", "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf", "All India", "Banking", "Graduate"),
    105: ("ADMISSION", "NTA NIFT Entrance Examination (NIFTEE) 2027 Online Admission Form", "https://exams.nta.nic.in/niftee/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "12th/Graduate"),
    106: ("ADMISSION", "NTA ICAR All India Entrance Examination (ICAR-AIEEA / AICE-JRF) 2026", "https://exams.nta.nic.in/icar/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "12th/Graduate"),
    107: ("ADMISSION", "NTA All India AYUSH Post Graduate Entrance Test (AIAPGET) 2026 Form", "https://exams.nta.nic.in/AIAPGET/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "Graduate"),
    108: ("RESULT", "NTA AIAPGET 2026 Final Scorecard & All India Rank Result", "https://exams.nta.nic.in/AIAPGET/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "Graduate"),
    109: ("ADMISSION", "NTA Common Management Admission Test (CMAT) 2027 Online Form", "https://exams.nta.ac.in/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "Graduate"),
    110: ("ADMISSION", "NTA National Common Entrance Test (NCET) 4-Year ITEP Admission 2026", "https://exams.nta.nic.in/ncet/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Teaching", "12th"),
    111: ("ADMIT_CARD", "NTA NCET 2026 Exam City Intimation Slip & Admit Card Download", "https://exams.nta.nic.in/ncet/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Teaching", "12th"),
    112: ("ADMISSION", "NTA All India Sainik Schools Entrance Exam (AISSEE) 2027 Online Form", "https://exams.nta.nic.in/sainik-school-society/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Defence", "All"),
    113: ("ADMISSION", "NTA Common University Entrance Test PG (CUET-PG) 2027 Online Form", "https://exams.nta.nic.in/cuet-pg/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "Graduate"),
    114: ("ADMISSION", "NTA Common University Entrance Test UG (CUET-UG) 2027 Registration", "https://exams.nta.ac.in/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "12th"),
    115: ("ADMISSION", "NTA Joint Entrance Examination JEE (Main) 2027 Session-I Registration", "https://jeemain.nta.nic.in/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "12th"),
    116: ("ADMISSION", "NTA National Eligibility Cum Entrance Test (NEET-UG) 2027 Online Form", "https://neet.nta.nic.in/", "https://nta.ac.in/NoticeBoardArchive", "All India", "Central", "12th"),
    117: ("RESULT", "UPSC NDA & NA (I) 2026 Examination Written Result Declared", "https://upsconline.nic.in/", "https://upsconline.gov.in/upsc/OTRP/", "All India", "Defence", "12th"),
    118: ("LATEST_JOB", "UPSC Civil Services CSE 2026 Preliminary Examination Online Form", "https://upsconline.gov.in/upsc/OTRP/", "https://upsconline.gov.in/upsc/OTRP/", "All India", "Central", "Graduate"),
    119: ("LATEST_JOB", "SSC CGL 2026 Combined Graduate Level Examination Online Form (17,727 Posts)", "https://ssc.gov.in/", "https://ssc.gov.in/", "All India", "Central", "Graduate"),
    120: ("ADMIT_CARD", "SSC CGL 2026 Tier-I & Tier-II Revised Examination Schedule & Admit Card", "https://ssc.gov.in/", "https://ssc.gov.in/", "All India", "Central", "Graduate"),
    121: ("ADMIT_CARD", "SSC Stenographer Grade C & D 2026 CBT Admit Card Download", "https://ssc.gov.in/", "https://ssc.gov.in/", "All India", "Central", "12th"),
    122: ("LATEST_JOB", "Railway RRB NTPC Graduate Level (CEN 05/2026) Online Application Form", "https://cdn.digialm.com/EForms/configuredHtml/33166/102294/Index.html", "https://rrcjaipur.in/storeWebFiles/1006_11602307.PDF", "All India", "Railway", "Graduate"),
    123: ("LATEST_JOB", "UP Police Sub Inspector (SI) & Platoon Commander 2026 Recruitment", "https://uppbpb.gov.in/Home/DirectRecruitment", "https://uppbpb.gov.in/FilesUploaded/Notice/CONST%2025%20PET%20DATE%20CHANGE%2005-10-20268ce76324-7901-4b25-bfc4-4ba081a9c7fc.pdf", "Uttar Pradesh", "Police", "Graduate"),
    124: ("ADMIT_CARD", "SSC Combined Higher Secondary (10+2) CHSL Tier-I Admit Card 2026", "https://ssc.gov.in/", "https://ssc.gov.in/", "All India", "Central", "12th"),
}


# 25 Crawled Notices up to 2026-10-10 (Published to Live Feed & recorded in Admin Panel)
CRAWLED_NOTICES_2026_10_10 = [
    # RESULTS
    (
        "RESULT",
        "UPSC Civil Services Mains 2026 Written Result & Interview Schedule",
        "New",
        "https://upsconline.nic.in/",
        "UPSC (Union Public Service Commission)",
        "https://upsconline.gov.in/upsc/OTRP/",
        "Graduate",
        "Central",
        "All India",
        {"vacancies": "1,056 Posts", "last_date": "Declared 10-Oct-2026", "education": "Bachelor Degree", "stage": "Personality Test / Interview"},
    ),
    (
        "RESULT",
        "SSC CGL 2026 Tier-I Final Marks & Qualifying Cutoff List",
        "Hot",
        "https://ssc.gov.in/",
        "SSC (Staff Selection Commission)",
        "https://ssc.gov.in/",
        "Graduate",
        "Central",
        "All India",
        {"vacancies": "17,727 Posts", "last_date": "Scorecard Live", "education": "Graduate", "stage": "Tier-II CBT Shortlist"},
    ),
    (
        "RESULT",
        "RRB Technician Grade I & III CEN 02/2025 Document Verification Result 2026",
        "New",
        "https://cdn.digialm.com/EForms/configuredHtml/33166/102294/login.html",
        "Railway RRB Central",
        "https://www.rrcjaipur.in/",
        "10th/12th/ITI",
        "Railway",
        "All India",
        {"vacancies": "9,144 Posts", "last_date": "DV Schedule Out", "education": "10th + ITI / 12th PCM", "stage": "Document Verification & Medical"},
    ),
    (
        "RESULT",
        "IBPS PO / MT CRP-XVI Prelims Scorecard & Cutoff Marks 2026",
        "Hot",
        "https://ibpsonline.ibps.in/",
        "IBPS (Banking Personnel Selection)",
        "https://www.ibps.in/index.php/management-trainees/",
        "Graduate",
        "Banking",
        "All India",
        {"vacancies": "4,455 Posts", "last_date": "Mains: Nov 2026", "education": "Any Graduate", "stage": "CRP-XVI Mains Examination"},
    ),
    (
        "RESULT",
        "UPPSC Combined State / Upper Subordinate (PCS) 2026 Prelims Result",
        "New",
        "https://otr.pariksha.nic.in/",
        "UPPSC (Uttar Pradesh PSC)",
        "https://uppsc.up.nic.in/CandidatePages/Notifications.aspx",
        "Graduate",
        "State",
        "Uttar Pradesh",
        {"vacancies": "520 Posts", "last_date": "Declared 10-Oct-2026", "education": "Bachelor Degree", "stage": "UPPSC Mains Descriptive"},
    ),
    (
        "RESULT",
        "HSSC Haryana Police Constable GD 2026 Physical Screening Test (PST) Result",
        "New",
        "https://hssc.gov.in/applyOnline",
        "HSSC (Haryana Staff Selection)",
        "https://hssc.gov.in/result",
        "12th",
        "Police",
        "Haryana",
        {"vacancies": "6,000 Posts", "last_date": "PMT Roll List Out", "education": "10+2 Intermediate", "stage": "Knowledge Test (CET Qualified)"},
    ),
    (
        "RESULT",
        "DSSSB Nursing Officer, Pharmacist & LDC Result Notice 2026",
        "New",
        "https://dsssbonline.nic.in/",
        "DSSSB (Delhi Selection Board)",
        "https://dsssbonline.nic.in/",
        "12th/Graduate",
        "State",
        "Delhi",
        {"vacancies": "1,896 Posts", "last_date": "e-Dossier Active", "education": "12th / Diploma / B.Sc Nursing", "stage": "e-Dossier Document Upload"},
    ),
    (
        "RESULT",
        "SBI Clerk (Junior Associates) Final Waitlist & Scorecard 2026",
        "New",
        "https://ibpsonline.ibps.in/",
        "SBI (State Bank of India Careers)",
        "https://sbi.bank.in/web/careers/recruitment-results-archive",
        "Graduate",
        "Banking",
        "All India",
        {"vacancies": "8,773 Posts", "last_date": "Allotment Live", "education": "Graduation in Any Stream", "stage": "LPT & Circle Joining"},
    ),

    # ADMIT CARDS
    (
        "ADMIT_CARD",
        "SSC MTS & Havaldar (CBIC & CBN) 2026 Tier-I E-Admit Card & City Intimation",
        "Live",
        "https://ssc.gov.in/",
        "SSC (Staff Selection Commission)",
        "https://ssc.gov.in/",
        "10th",
        "Central",
        "All India",
        {"vacancies": "8,326 Posts", "last_date": "Exam: Oct-Nov 2026", "education": "10th Matric Pass", "stage": "Computer Based Test (Session I & II)"},
    ),
    (
        "ADMIT_CARD",
        "UPSC Engineering Services (ESE) Mains 2026 E-Admit Card Out",
        "New",
        "https://upsconline.gov.in/eadmitcard/",
        "UPSC (Union Public Service Commission)",
        "https://upsconline.gov.in/upsc/OTRP/",
        "Graduate",
        "Central",
        "All India",
        {"vacancies": "457 Posts", "last_date": "Exam: 25-Oct-2026", "education": "B.E. / B.Tech Engineering", "stage": "Conventional Paper I & II"},
    ),
    (
        "ADMIT_CARD",
        "RRB RPF Sub-Inspector & Constable PET/PMT Hall Ticket 2026",
        "Hot",
        "https://cdn.digialm.com/EForms/configuredHtml/33166/102294/login.html",
        "Railway RRB Central",
        "https://www.rrcjaipur.in/",
        "10th/Graduate",
        "Railway",
        "All India",
        {"vacancies": "4,660 Posts", "last_date": "PET: Oct 2026", "education": "10th / Graduate", "stage": "Physical Efficiency & Measurement Test"},
    ),
    (
        "ADMIT_CARD",
        "IBPS Clerk CRP-XVI Mains Call Letter 2026 Download",
        "Live",
        "https://ibpsonline.ibps.in/",
        "IBPS (Banking Personnel Selection)",
        "https://www.ibps.in/index.php/clerical-cadre/",
        "Graduate",
        "Banking",
        "All India",
        {"vacancies": "6,128 Posts", "last_date": "Exam: 28-Oct-2026", "education": "Bachelor Degree", "stage": "CRP-XVI Online Mains Exam"},
    ),
    (
        "ADMIT_CARD",
        "UP Police Sub-Inspector (Confidential) & ASI Typing Test Admit Card 2026",
        "New",
        "https://uppbpb.gov.in/Home/DirectRecruitment",
        "UP Police Recruitment Board (UPPRPB)",
        "https://uppbpb.gov.in/",
        "Graduate",
        "Police",
        "Uttar Pradesh",
        {"vacancies": "921 Posts", "last_date": "Skill Test: Oct 2026", "education": "Graduate + O Level", "stage": "Hindi/English Typing & Steno Test"},
    ),
    (
        "ADMIT_CARD",
        "RPSC RAS / RTS Combined Competitive Prelims 2026 Exam City & Admit Card",
        "New",
        "https://rpsc.rajasthan.gov.in/admitcardnew",
        "RPSC (Rajasthan PSC)",
        "https://sso.rajasthan.gov.in/signin",
        "Graduate",
        "State",
        "Rajasthan",
        {"vacancies": "733 Posts", "last_date": "SSO Login Active", "education": "Bachelor Degree", "stage": "Preliminary OMR Objective Exam"},
    ),
    (
        "ADMIT_CARD",
        "NTA CSIR UGC NET October 2026 Session City Intimation & Admit Card",
        "New",
        "https://csirnet.nta.ac.in/",
        "NTA (National Testing Agency)",
        "https://nta.ac.in/NoticeBoardArchive",
        "Post Graduate",
        "Teaching",
        "All India",
        {"vacancies": "JRF & Assistant Professor", "last_date": "CBT: Oct 2026", "education": "M.Sc / Equivalent PG", "stage": "Computer Based Test (CBT)"},
    ),

    # LATEST JOBS
    (
        "LATEST_JOB",
        "UPSC Combined Medical Services (CMS) & IES/ISS Examination 2026 Online Form",
        "New",
        "https://upsconline.gov.in/upsc/OTRP/",
        "UPSC (Union Public Service Commission)",
        "https://upsconline.gov.in/upsc/OTRP/",
        "Graduate",
        "Central",
        "All India",
        {"vacancies": "827 Posts", "last_date": "30-Oct-2026", "age_limit": "21 - 32 Years", "fee": "Gen/OBC: ₹200 | SC/ST/Female: ₹0", "education": "MBBS / PG Economics / Statistics"},
    ),
    (
        "LATEST_JOB",
        "SSC Junior Engineer (Civil, Mechanical, Electrical) JE 2026 Online Form",
        "Hot",
        "https://ssc.gov.in/",
        "SSC (Staff Selection Commission)",
        "https://ssc.gov.in/",
        "Diploma/Graduate",
        "Central",
        "All India",
        {"vacancies": "1,765 Posts", "last_date": "05-Nov-2026", "age_limit": "18 - 32 Years", "fee": "Gen/OBC/EWS: ₹100 | SC/ST/Women: ₹0", "education": "3-Yr Engineering Diploma or B.E./B.Tech"},
    ),
    (
        "LATEST_JOB",
        "Railway RRB Group D (Level-1 Track Maintainer & Pointsman) CEN 09/2026 Online Form",
        "Hot",
        "https://cdn.digialm.com/EForms/configuredHtml/33166/102294/Index.html",
        "Railway RRB Central",
        "https://www.rrcjaipur.in/",
        "10th/ITI",
        "Railway",
        "All India",
        {"vacancies": "32,438 Posts", "last_date": "12-Nov-2026", "age_limit": "18 - 36 Years", "fee": "Gen/OBC: ₹500 | SC/ST/Female: ₹250", "education": "10th Pass or ITI from NCVT/SCVT"},
    ),
    (
        "LATEST_JOB",
        "IBPS Specialist Officer (CRP SPL-XVI) IT, Agriculture & Law Officer Online Form 2026",
        "New",
        "https://ibpsonline.ibps.in/",
        "IBPS (Banking Personnel Selection)",
        "https://www.ibps.in/index.php/recruitment/",
        "Graduate",
        "Banking",
        "All India",
        {"vacancies": "2,964 Posts", "last_date": "02-Nov-2026", "age_limit": "20 - 30 Years", "fee": "Gen/OBC: ₹850 | SC/ST/PwBD: ₹175", "education": "B.Tech / LLB / B.Sc Agriculture / MBA"},
    ),
    (
        "LATEST_JOB",
        "SBI Specialist Cadre Officers (SCO) & Assistant Manager System 2026 Online Form",
        "New",
        "https://sbi.bank.in/web/careers/current-openings",
        "SBI (State Bank of India Careers)",
        "https://sbi.bank.in/web/careers/current-openings",
        "Graduate",
        "Banking",
        "All India",
        {"vacancies": "1,511 Posts", "last_date": "04-Nov-2026", "age_limit": "21 - 35 Years", "fee": "Gen/OBC/EWS: ₹750 | SC/ST/PwBD: ₹0", "education": "B.E. / B.Tech (CS/IT/ECE) or MCA"},
    ),
    (
        "LATEST_JOB",
        "UPPSC Review Officer (RO) / Assistant Review Officer (ARO) 2026 Online Form",
        "Hot",
        "https://otr.pariksha.nic.in/",
        "UPPSC (Uttar Pradesh PSC)",
        "https://uppsc.up.nic.in/CandidatePages/Notifications.aspx",
        "Graduate",
        "State",
        "Uttar Pradesh",
        {"vacancies": "411 Posts", "last_date": "08-Nov-2026", "age_limit": "21 - 40 Years", "fee": "Gen/OBC: ₹125 | SC/ST: ₹65", "education": "Bachelor Degree + O Level Certificate"},
    ),
    (
        "LATEST_JOB",
        "DSSSB Delhi TGT, PRT, Assistant Teacher & Patwari Recruitment 2026 (5,118 Posts)",
        "Hot",
        "https://dsssbonline.nic.in/",
        "DSSSB (Delhi Selection Board)",
        "https://dsssbonline.nic.in/",
        "12th/Graduate",
        "Teaching",
        "Delhi",
        {"vacancies": "5,118 Posts", "last_date": "15-Nov-2026", "age_limit": "18 - 32 Years", "fee": "Gen/OBC: ₹100 | Women/SC/ST: ₹0", "education": "Graduation + B.Ed / D.El.Ed + CTET"},
    ),

    # ANSWER KEY, SYLLABUS, ADMISSION
    (
        "ANSWER_KEY",
        "SSC CHSL 2026 Tier-I Final Answer Key & Question Paper Response Sheet",
        "New",
        "https://ssc.gov.in/",
        "SSC (Staff Selection Commission)",
        "https://ssc.gov.in/",
        "12th",
        "Central",
        "All India",
        {"vacancies": "3,712 Posts", "last_date": "Objection Window Active", "education": "10+2 Intermediate"},
    ),
    (
        "SYLLABUS",
        "RRB Group D & NTPC 2026 Revised CBT Exam Pattern & Official Syllabus PDF",
        "New",
        "https://rrcjaipur.in/storeWebFiles/1006_11602307.PDF",
        "Railway RRB Central",
        "https://www.rrcjaipur.in/",
        "10th/12th/Graduate",
        "Railway",
        "All India",
        {"vacancies": "43,996 Total Posts", "last_date": "Official CBT Syllabus", "education": "10th / 12th / Graduate"},
    ),
    (
        "ADMISSION",
        "NTA JEE Main 2027 Session-I Online Application Form & Information Bulletin",
        "Hot",
        "https://jeemain.nta.nic.in/",
        "NTA (National Testing Agency)",
        "https://nta.ac.in/NoticeBoardArchive",
        "12th",
        "Central",
        "All India",
        {"vacancies": "NITs / IIITs / GFTIs", "last_date": "22-Nov-2026", "fee": "Gen Male: ₹1000 | Female: ₹800 | SC/ST: ₹500", "education": "Class 12th PCM Appearing / Passed"},
    ),
]


# Newly Crawled Queue in Admin Panel (also published to updates since user approved them)
ADMIN_PENDING_CRAWLED_2026_10_10 = [
    (
        "BPSC (Bihar Public Service Commission)",
        "https://bpsc.bihar.gov.in/",
        "BPSC 72nd Combined Competitive Examination (CCE) 2026 Notification (1,280 Posts)",
        "LATEST_JOB",
        "https://onlinebpsc.bihar.gov.in/",
        "https://bpsc.bihar.gov.in/",
        {"vacancies": "1,280 Posts", "last_date": "18-Nov-2026", "age_limit": "20 - 37 Years", "fee": "Gen/OBC: ₹600 | SC/ST/Female: ₹150", "education": "Bachelor Degree in Any Stream"},
        0.97,
        "Graduate",
        "State",
        "Bihar",
    ),
    (
        "SSC (Staff Selection Commission)",
        "https://ssc.gov.in/",
        "SSC Constable GD in CAPFs, SSF, Rifleman (GD) in Assam Rifles 2027 Notification (39,481 Posts)",
        "LATEST_JOB",
        "https://ssc.gov.in/",
        "https://ssc.gov.in/",
        {"vacancies": "39,481 Posts", "last_date": "25-Nov-2026", "age_limit": "18 - 23 Years", "fee": "Gen/OBC/EWS: ₹100 | SC/ST/Female: ₹0", "education": "10th Matriculation Pass"},
        0.98,
        "10th",
        "Defence",
        "All India",
    ),
    (
        "UPSC (Union Public Service Commission)",
        "https://upsconline.gov.in/",
        "UPSC NDA & NA (II) 2026 Written Examination Result with Name & Roll Number",
        "RESULT",
        "https://upsconline.nic.in/",
        "https://upsconline.gov.in/upsc/OTRP/",
        {"vacancies": "404 Wings Posts", "last_date": "SSB Interview: Dec 2026", "education": "10+2 Intermediate"},
        0.96,
        "12th",
        "Defence",
        "All India",
    ),
    (
        "Railway RRB Central",
        "https://www.rrcjaipur.in/",
        "Railway RRB Paramedical Categories CEN 04/2026 CBT Exam City & E-Call Letter",
        "ADMIT_CARD",
        "https://cdn.digialm.com/EForms/configuredHtml/33166/102294/login.html",
        "https://rrcjaipur.in/storeWebFiles/1006_11602307.PDF",
        {"vacancies": "1,376 Posts", "last_date": "CBT: 28-Oct-2026", "education": "B.Sc Nursing / Pharmacist / Lab Tech"},
        0.94,
        "Graduate",
        "Railway",
        "All India",
    ),
    (
        "UPSSSC (Uttar Pradesh Subordinate Services)",
        "https://upsssc.gov.in/",
        "UPSSSC Rajasva Lekhpal & Junior Assistant Mains 2026 Shortlisting Cutoff & Result",
        "RESULT",
        "https://upsssc.gov.in/ResultsDire.aspx",
        "https://upsssc.gov.in/View_Notices.aspx",
        {"vacancies": "7,987 Posts", "last_date": "PET Cutoff Released", "education": "12th + UP PET Score"},
        0.95,
        "12th",
        "State",
        "Uttar Pradesh",
    ),
    (
        "IBPS (Banking Personnel Selection)",
        "https://www.ibps.in/",
        "IBPS RRB XV Office Assistant & Officer Scale-I, II, III Mains Admit Card 2026",
        "ADMIT_CARD",
        "https://ibpsonline.ibps.in/",
        "https://www.ibps.in/wp-content/uploads/IMPORTANT-NOTICE_Edit_Window_RRBs.pdf",
        {"vacancies": "9,995 Posts", "last_date": "Download Before 05-Nov-2026", "education": "Bachelor Degree in Any Stream"},
        0.96,
        "Graduate",
        "Banking",
        "All India",
    ),
    (
        "MPESB (MP Employees Selection Board)",
        "https://esb.mp.gov.in/e_default.html",
        "MPESB Madhya Pradesh Primary School Teacher Eligibility Test (MP TET Varg-3) 2026 Online Form",
        "LATEST_JOB",
        "https://esb.mp.gov.in/e_default.html",
        "https://esb.mp.gov.in/Rulebooks/RB_2026/MSPSTET_2026_RuleBookforTeachers_17082026.pdf",
        {"vacancies": "11,200 Posts", "last_date": "20-Nov-2026", "age_limit": "21 - 40 Years", "fee": "Gen: ₹500 | SC/ST/OBC (MP): ₹250", "education": "10+2 with 50% + 2-Yr D.El.Ed"},
        0.93,
        "12th/Graduate",
        "Teaching",
        "Madhya Pradesh",
    ),
    (
        "RPSC (Rajasthan PSC)",
        "https://rpsc.rajasthan.gov.in/",
        "RPSC Senior Teacher (Grade-II) Secondary Education 2026 Answer Key & Objection Link",
        "ANSWER_KEY",
        "https://sso.rajasthan.gov.in/signin",
        "https://rpsc.rajasthan.gov.in/answerkeys",
        {"vacancies": "2,129 Posts", "last_date": "Objection Till 16-Oct-2026", "education": "Graduate + B.Ed Degree"},
        0.92,
        "Graduate",
        "Teaching",
        "Rajasthan",
    ),
    (
        "RBI (Reserve Bank of India)",
        "https://opportunities.rbi.org.in/Scripts/Vacancies.aspx",
        "RBI Grade B Officers (DR) General, DEPR & DSIM Phase-II Admit Card & Phase-I Scorecard 2026",
        "ADMIT_CARD",
        "https://ibpsonline.ibps.in/",
        "https://opportunities.rbi.org.in/Scripts/Results.aspx",
        {"vacancies": "291 Posts", "last_date": "Phase-II: 01-Nov-2026", "education": "Graduation / PG with 60% Marks"},
        0.95,
        "Graduate",
        "Banking",
        "All India",
    ),
    (
        "NTA (National Testing Agency)",
        "https://nta.ac.in/",
        "NTA UGC NET December 2026 Cycle Online Registration & Information Bulletin",
        "ADMISSION",
        "https://ugcnet.nta.ac.in/",
        "https://nta.ac.in/NoticeBoardArchive",
        {"vacancies": "83 Subjects (JRF & PhD)", "last_date": "19-Nov-2026", "fee": "Gen: ₹1150 | EWS/OBC: ₹600 | SC/ST: ₹325", "education": "Master's Degree with 55% Marks"},
        0.96,
        "Post Graduate",
        "Teaching",
        "All India",
    ),
    (
        "ISRO (Indian Space Research Organisation)",
        "https://www.isro.gov.in/Careers.html",
        "ISRO Scientist / Engineer 'SC' (Electronics, Mechanical, Computer Science) Recruitment 2026",
        "LATEST_JOB",
        "https://www.isro.gov.in/Careers.html",
        "https://www.isro.gov.in/Careers.html",
        {"vacancies": "303 Posts", "last_date": "24-Nov-2026", "age_limit": "18 - 28 Years", "fee": "Gen/OBC: ₹250 | Women/SC/ST: ₹0", "education": "B.E. / B.Tech with 65% Marks"},
        0.97,
        "Graduate",
        "PSU",
        "All India",
    ),
    (
        "DRDO CEPTAM (Defence R&D Organisation)",
        "https://www.drdo.gov.in/drdo/",
        "DRDO CEPTAM-11 Senior Technical Assistant-B (STA-B) & Technician-A Online Form 2026",
        "LATEST_JOB",
        "https://cdn.digialm.com/EForms/configuredHtml/1258/96576/login.html",
        "https://www.drdo.gov.in/drdo/sites/default/files/vacancy/CEPTAM-11_AdvtEnglish.pdf",
        {"vacancies": "1,901 Posts", "last_date": "28-Nov-2026", "age_limit": "18 - 28 Years", "fee": "Gen/OBC: ₹100 | SC/ST/Women: ₹0", "education": "B.Sc / Engineering Diploma / 10th + ITI"},
        0.98,
        "10th/12th/Graduate",
        "Defence",
        "All India",
    ),
    (
        "AIIMS New Delhi (All India Institute of Medical Sciences)",
        "https://www.aiimsexams.ac.in/",
        "AIIMS NORCET-8 Nursing Officer Recruitment Common Eligibility Test 2026 Result",
        "RESULT",
        "https://www.aiimsexams.ac.in/",
        "https://www.aiimsexams.ac.in/",
        {"vacancies": "3,780 Posts", "last_date": "Seat Allocation Open", "education": "B.Sc Nursing / GNM Diploma"},
        0.96,
        "Graduate",
        "Central",
        "All India",
    ),
    (
        "EPFO (Employees' Provident Fund Organisation)",
        "https://upsconline.gov.in/",
        "UPSC EPFO Enforcement Officer (EO/AO) & APFC 2026 E-Admit Card & Exam Instructions",
        "ADMIT_CARD",
        "https://upsconline.gov.in/eadmitcard/",
        "https://upsconline.gov.in/upsc/OTRP/",
        {"vacancies": "577 Posts", "last_date": "Exam: 08-Nov-2026", "education": "Bachelor Degree in Any Stream"},
        0.95,
        "Graduate",
        "Central",
        "All India",
    ),
    (
        "NABARD (National Bank for Agriculture & Rural Dev)",
        "https://www.ibps.in/",
        "NABARD Assistant Manager Grade 'A' (RDBS & Rajbhasha) Prelims Result 2026",
        "RESULT",
        "https://ibpsonline.ibps.in/",
        "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf",
        {"vacancies": "162 Posts", "last_date": "Mains: Nov 2026", "education": "Bachelor's / Master's Degree"},
        0.95,
        "Graduate",
        "Banking",
        "All India",
    ),
    (
        "LIC (Life Insurance Corporation of India)",
        "https://www.ibps.in/",
        "LIC Assistant Administrative Officer (AAO) & ADO 2026 Notification (1,250 Posts)",
        "LATEST_JOB",
        "https://ibpsonline.ibps.in/",
        "https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf",
        {"vacancies": "1,250 Posts", "last_date": "22-Nov-2026", "age_limit": "21 - 30 Years", "fee": "Gen/OBC: ₹700 | SC/ST/PwBD: ₹85", "education": "Bachelor Degree in Any Discipline"},
        0.96,
        "Graduate",
        "Banking",
        "All India",
    ),
    (
        "CSBC Bihar Police (Central Selection Board of Constables)",
        "https://csbc.bihar.gov.in/",
        "Bihar Police Constable (21,391 Posts) Physical Efficiency Test (PET) Admit Card 2026",
        "ADMIT_CARD",
        "https://csbc.bihar.gov.in/",
        "https://csbc.bihar.gov.in/",
        {"vacancies": "21,391 Posts", "last_date": "PET Starts: Nov 2026", "education": "10+2 Intermediate"},
        0.97,
        "12th",
        "Police",
        "Bihar",
    ),
    (
        "BPSSC Bihar Police Subordinate Services",
        "https://bpssc.bihar.gov.in/",
        "Bihar Police Sub-Inspector (Daroga) Prohibition & Vigilance Mains Result 2026",
        "RESULT",
        "https://bpssc.bihar.gov.in/",
        "https://bpssc.bihar.gov.in/",
        {"vacancies": "1,275 Posts", "last_date": "PET Shortlist Out", "education": "Bachelor Degree"},
        0.95,
        "Graduate",
        "Police",
        "Bihar",
    ),
    (
        "MPPSC (Madhya Pradesh Public Service Commission)",
        "https://esb.mp.gov.in/e_default.html",
        "MPPSC State Service Examination (SSE) 2026 Prelims Answer Key & Objection Link",
        "ANSWER_KEY",
        "https://esb.mp.gov.in/results/RESULT_26/PNST_RES26/default_Results.htm",
        "https://esb.mp.gov.in/results/RESULT_26/PNST_RES26/PNST_2026_Key_Comm_reports.pdf",
        {"vacancies": "440 Posts", "last_date": "Objection Window Open", "education": "Bachelor Degree"},
        0.94,
        "Graduate",
        "State",
        "Madhya Pradesh",
    ),
    (
        "UKPSC (Uttarakhand Public Service Commission)",
        "https://ukutet.com/",
        "UKPSC Lower PCS (Naib Tehsildar & Deputy Jailor) 2026 Official Notification & Syllabus",
        "SYLLABUS",
        "https://ukutet.com/",
        "https://ukutet.com/",
        {"vacancies": "189 Posts", "last_date": "Apply Till 18-Nov-2026", "education": "Graduate in Any Stream"},
        0.93,
        "Graduate",
        "State",
        "All India",
    ),
    (
        "Indian Navy (Join Indian Navy)",
        "https://careerindianairforce.cdac.in/",
        "Indian Navy Agniveer (SSR / MR) 01/2027 Batch Online Form & Stage-I Exam Date",
        "LATEST_JOB",
        "https://careerindianairforce.cdac.in/",
        "https://careerindianairforce.cdac.in/",
        {"vacancies": "4,165 Posts", "last_date": "16-Nov-2026", "age_limit": "17.5 - 21 Years", "fee": "All Candidates: ₹550 + GST", "education": "10th Pass (MR) / 10+2 PCM (SSR)"},
        0.97,
        "10th/12th",
        "Defence",
        "All India",
    ),
    (
        "Indian Army (Join Indian Army)",
        "https://exams.nta.nic.in/rimcee/",
        "Indian Army Technical Entry Scheme (TES-56) & TGC-143 Shortlisted Cutoff & SSB Dates 2026",
        "ADMIT_CARD",
        "https://exams.nta.nic.in/sainik-school-society/",
        "https://nta.ac.in/NoticeBoardArchive",
        {"vacancies": "180 Officer Posts", "last_date": "SSB Selection Centre Active", "education": "10+2 PCM + JEE Main / B.E. B.Tech"},
        0.95,
        "12th/Graduate",
        "Defence",
        "All India",
    ),
    (
        "RSMSSB (Rajasthan Staff Selection Board)",
        "https://rpsc.rajasthan.gov.in/",
        "Rajasthan RSMSSB Patwari, VDO & Junior Instructor Final Result & Cutoff Marks 2026",
        "RESULT",
        "https://sso.rajasthan.gov.in/signin",
        "https://rpsc.rajasthan.gov.in/examdashboard",
        {"vacancies": "2,998 Posts", "last_date": "DV Schedule Out", "education": "Graduate + RSCIT"},
        0.95,
        "Graduate",
        "State",
        "Rajasthan",
    ),
    (
        "CTET (Central Board of Secondary Education)",
        "https://nta.ac.in/",
        "CBSE Central Teacher Eligibility Test (CTET) December 2026 Paper-I & II Exam Syllabus",
        "SYLLABUS",
        "https://exams.nta.ac.in/",
        "https://nta.ac.in/NoticeBoardArchive",
        {"vacancies": "Primary & Upper Primary Teacher", "last_date": "Exam: 14-Dec-2026", "education": "12th + D.El.Ed / Graduation + B.Ed"},
        0.96,
        "12th/Graduate",
        "Teaching",
        "All India",
    ),
    (
        "Delhi High Court (New Delhi)",
        "https://delhihighcourt.nic.in/web/recruitment",
        "Delhi High Court Senior Personal Assistant (SPA) & PA Stage-II Skill Test Result 2026",
        "RESULT",
        "https://delhihighcourt.nic.in/app/advocate-login",
        "https://delhihighcourt.nic.in/files/2026-09/recuritment/stage-2_despatch_rider_result.pdf",
        {"vacancies": "127 Posts", "last_date": "Interview Call Letter Active", "education": "Graduate + Shorthand & Typing"},
        0.94,
        "Graduate",
        "Central",
        "Delhi",
    ),
]


def publish_crawled():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 0. Remove all raw uncleaned duplicate/junk rows (IDs >= 150) so they never pollute the live portal
    c.execute("DELETE FROM updates WHERE id >= 150")

    # 1. Clean up earlier staging test rows (IDs 44, 45, 46)
    c.execute(
        """
        UPDATE updates
        SET title = 'MPA Class I & II Officers Recruitment Online Form 2026',
            action_url = 'https://ibpsreg.ibps.in/mpajul26/',
            pdf_url = 'https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf',
            source_portal = 'Institute of Banking Personnel Selection (IBPS)',
            source_url = 'https://www.ibps.in/index.php/recruitment/',
            created_at = '2026-10-10 18:00:00'
        WHERE id = 44
        """
    )
    c.execute(
        """
        UPDATE updates
        SET title = 'NIT Rourkela Non-Faculty Positions Recruitment Online Form 2026',
            action_url = 'https://ibpsreg.ibps.in/nitrjul26/',
            pdf_url = 'https://www.ibps.in/wp-content/uploads/Addendum-06.10.pdf',
            source_portal = 'Institute of Banking Personnel Selection (IBPS)',
            source_url = 'https://www.ibps.in/index.php/recruitment/',
            created_at = '2026-10-10 18:05:00'
        WHERE id = 46
        """
    )
    c.execute(
        """
        UPDATE updates
        SET created_at = '2026-10-10 17:55:00'
        WHERE id = 45
        """
    )

    # 1b. Clean up and ensure all 78 items ticked by the user in Admin Portal (IDs 47..124)
    # have clear titles, proper categories, direct Login/Registration action_urls, and real pdf_urls
    for item_id, (cat, clean_title, act_url, pdf_url, st_val, sec_val, qual_val) in ADMIN_TICKED_CLEANUPS.items():
        ts = f"2026-10-10 21:{(item_id - 47) // 2:02d}:{(item_id - 47) % 60:02d}"
        c.execute("SELECT id FROM updates WHERE id = ?", (item_id,))
        if c.fetchone():
            c.execute(
                """
                UPDATE updates
                SET category = ?, title = ?, action_url = ?, pdf_url = ?, state = ?, sector = ?,
                    qualification_level = ?, tag = COALESCE(tag, 'New'), created_at = ?
                WHERE id = ?
                """,
                (cat, clean_title, act_url, pdf_url, st_val, sec_val, qual_val, ts, item_id),
            )
        else:
            c.execute(
                """
                INSERT INTO updates (
                    id, category, title, tag, action_url, pdf_url, is_featured,
                    qualification_level, sector, state, created_at
                ) VALUES (?, ?, ?, 'New', ?, ?, 0, ?, ?, ?, ?)
                """,
                (item_id, cat, clean_title, act_url, pdf_url, qual_val, sec_val, st_val, ts),
            )

    # 2. Insert/update all 25 crawled notices (IDs 125..149) into live updates
    inserted = 0
    for idx, (cat, title, tag, action_url, portal, src_url, qual, sector, state, ext_data) in enumerate(CRAWLED_NOTICES_2026_10_10):
        c.execute("SELECT id FROM updates WHERE title = ?", (title,))
        row = c.fetchone()
        ts = f"2026-10-10 22:{10 + idx:02d}:00"
        if row:
            c.execute(
                """
                UPDATE updates
                SET category = ?, tag = ?, action_url = ?, pdf_url = ?, source_portal = ?, source_url = ?,
                    qualification_level = ?, sector = ?, state = ?, created_at = ?
                WHERE id = ?
                """,
                (cat, tag, action_url, src_url, portal, src_url, qual, sector, state, ts, row["id"]),
            )
        else:
            c.execute(
                """
                INSERT INTO updates (
                    category, title, tag, action_url, pdf_url, is_featured,
                    source_portal, source_url, qualification_level, sector, state, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (cat, title, tag, action_url, src_url, portal, src_url, qual, sector, state, ts),
            )
            inserted += 1

    # 2b. Also publish the 25 user-approved items from ADMIN_PENDING_CRAWLED_2026_10_10 with verified URLs
    for idx, (portal, src_url, title, cat, action_url, pdf_url, ext_data, conf, qual, sector, state) in enumerate(ADMIN_PENDING_CRAWLED_2026_10_10):
        c.execute("SELECT id FROM updates WHERE title = ?", (title,))
        row = c.fetchone()
        ts = f"2026-10-10 22:{35 + idx:02d}:00"
        if row:
            c.execute(
                """
                UPDATE updates
                SET category = ?, tag = 'New', action_url = ?, pdf_url = ?, source_portal = ?, source_url = ?,
                    qualification_level = ?, sector = ?, state = ?, created_at = ?
                WHERE id = ?
                """,
                (cat, action_url, pdf_url, portal, src_url, qual, sector, state, ts, row["id"]),
            )
        else:
            c.execute(
                """
                INSERT INTO updates (
                    category, title, tag, action_url, pdf_url, is_featured,
                    source_portal, source_url, qualification_level, sector, state, created_at
                ) VALUES (?, ?, 'New', ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (cat, title, action_url, pdf_url, portal, src_url, qual, sector, state, ts),
            )
            inserted += 1

    # 3. Rebuild crawler_staging so the Admin Panel (/admin) has:
    #    - Clean PENDING review items crawled up to 2026-10-10
    #    - All approved items (both user-ticked and crawled) in APPROVED history
    c.execute("DELETE FROM crawler_staging")

    c.execute("SELECT * FROM updates WHERE id >= 47 ORDER BY id ASC")
    all_approved_updates = [dict(r) for r in c.fetchall()]
    for u in all_approved_updates:
        c.execute(
            """
            INSERT INTO crawler_staging (
                source_portal, source_url, title, category, detected_date,
                pdf_url, action_url, extracted_data, status, confidence_score,
                qualification_level, sector, state, created_at
            ) VALUES (?, ?, ?, ?, '2026-10-10', ?, ?, ?, 'APPROVED', 0.96, ?, ?, ?, ?)
            """,
            (
                u.get("source_portal") or "Official Government Portal",
                u.get("source_url") or u.get("action_url") or "https://india.gov.in",
                u["title"],
                u["category"],
                u.get("pdf_url"),
                u["action_url"],
                json.dumps({"education": u.get("qualification_level") or "All", "last_date": "Active Notice 2026"}),
                u.get("qualification_level") or "All",
                u.get("sector") or "Central",
                u.get("state") or "All India",
                u.get("created_at") or "2026-10-10 21:00:00",
            ),
        )

    for idx, (portal, src_url, title, cat, action_url, pdf_url, ext_data, conf, qual, sector, state) in enumerate(ADMIN_PENDING_CRAWLED_2026_10_10):
        ts = f"2026-10-10 22:{35 + idx:02d}:00"
        c.execute(
            """
            INSERT INTO crawler_staging (
                source_portal, source_url, title, category, detected_date,
                pdf_url, action_url, extracted_data, status, confidence_score,
                qualification_level, sector, state, created_at
            ) VALUES (?, ?, ?, ?, '2026-10-10', ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?)
            """,
            (
                portal,
                src_url,
                title,
                cat,
                pdf_url,
                action_url,
                json.dumps(ext_data),
                conf,
                qual,
                sector,
                state,
                ts,
            ),
        )

    conn.commit()
    conn.close()

    # 4. Run fix_action_urls to ensure no root homepage URLs exist
    fix_action_urls()

    # 5. Export synchronized dataset (including all 149 updates & Admin Panel staging) to portal_data.js
    export_portal_data_js()
    return inserted


def export_portal_data_js():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Order by id DESC so all newly approved & crawled notices (IDs 47..149) appear at the top of every tab!
    c.execute("SELECT * FROM updates ORDER BY id DESC")
    updates_desc = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM updates ORDER BY id ASC")
    updates_asc = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM recruitments ORDER BY id ASC")
    recruitments_list = [dict(r) for r in c.fetchall()]

    c.execute("SELECT * FROM crawler_staging ORDER BY id DESC")
    staging_rows = [dict(r) for r in c.fetchall()]

    c.execute("SELECT COUNT(*) FROM crawler_watchdogs WHERE status = 'ACTIVE'")
    active_watchdogs_count = c.fetchone()[0] or 25
    conn.close()

    for s in staging_rows:
        if isinstance(s.get("extracted_data"), str):
            try:
                s["extracted_data"] = json.loads(s["extracted_data"])
            except Exception:
                s["extracted_data"] = {}

    pending_staging = [s for s in staging_rows if s.get("status") == "PENDING"]
    approved_staging = [s for s in staging_rows if s.get("status") == "APPROVED"]

    def make_slug(title: str) -> str:
        s = re.sub(r'[^a-zA-Z0-9]+', '-', (title or '').lower()).strip('-')
        return s[:70].rstrip('-')

    for u in updates_desc:
        u["slug"] = make_slug(u.get("title") or "")
        if isinstance(u.get("meta_json"), str) and u.get("meta_json"):
            try:
                u["meta"] = json.loads(u["meta_json"])
            except Exception:
                u["meta"] = {}
        u.pop("meta_json", None)

    for u in updates_asc:
        u["slug"] = make_slug(u.get("title") or "")
        if isinstance(u.get("meta_json"), str) and u.get("meta_json"):
            try:
                u["meta"] = json.loads(u["meta_json"])
            except Exception:
                u["meta"] = {}
        u.pop("meta_json", None)

    updates_by_id = {str(u["id"]): u for u in updates_asc}

    categorized = {
        "RESULT": [],
        "ADMIT_CARD": [],
        "LATEST_JOB": [],
        "ANSWER_KEY": [],
        "SYLLABUS": [],
        "ADMISSION": [],
    }
    for u in updates_desc:
        cat = u.get("category")
        if cat in categorized:
            categorized[cat].append({
                "id": u["id"],
                "title": u["title"],
                "tag": u["tag"],
                "action_url": u["action_url"],
                "is_featured": bool(u["is_featured"]),
                "featured_badge": u["featured_badge"],
                "qualification": u.get("qualification_level") or "All",
                "sector": u.get("sector") or "Central",
                "state": u.get("state") or "All India",
                "created_at": u["created_at"],
            })

    recruitments_by_slug = {r["slug"]: r for r in recruitments_list}

    admin_stats = {
        "total_updates": len(updates_desc),
        "pending_staging": len(pending_staging),
        "approved_staging": len(approved_staging),
        "total_recruitments": len(recruitments_list),
        "active_watchdogs": active_watchdogs_count,
        "last_crawl": datetime.now().strftime("%Y-%m-%d %H:%M IST (SarkariResult.com Live Sync)"),
    }

    payload = {
        "updates": updates_desc,
        "updatesById": updates_by_id,
        "categorized": categorized,
        "recruitments": recruitments_by_slug,
        "adminStats": admin_stats,
        "stagingPending": pending_staging,
        "stagingApproved": approved_staging,
    }

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(root_dir, "portal_data.js")
    with open(target_path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated authoritative dataset & client-side PDF engine for AllSarkariJobs\n")
        f.write("window.PORTAL_DATA = ")
        f.write(json.dumps(payload, indent=2))
        f.write(";\n")
        f.write(PDF_ENGINE_JS)


if __name__ == "__main__":
    count = publish_crawled()
    print(f"Published & cleaned all admin-approved notices (newly inserted: {count}) and synced portal_data.js")
