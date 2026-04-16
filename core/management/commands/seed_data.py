from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Project, BuildStage, GateChecklistItem, Task, Issue, TeamMember, NREItem, Customer, Milestone


class Command(BaseCommand):
    help = 'Seed the database with sample NPI projects'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database...')

        # Resolve or create PM users
        def get_user(username):
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={'first_name': username, 'is_staff': False},
            )
            return user

        u_ekaluk   = get_user('Ekaluk')
        u_natthida = get_user('Natthida')
        u_somchai  = get_user('Somchai')

        def get_customer(name):
            c, _ = Customer.objects.get_or_create(name=name)
            return c

        c_axis   = get_customer('Axis')
        c_hanwha = get_customer('Hanwha')
        c_bosch  = get_customer('Bosch')

        # Clear existing data
        Project.objects.all().delete()

        # ── Project 1: Greenland ─────────────────────────────────────
        p1 = Project.objects.create(
            name='Greenland', pgm=u_ekaluk, customer=c_axis,
            start_date=date(2025, 10, 1), end_date=date(2026, 6, 30),
            color='#34B27B', annual_volume=50000, annual_revenue=25000000, currency='THB',
        )
        p1.create_default_stages()

        # Stages
        etb1 = BuildStage.objects.get(project=p1, name='ETB')
        etb1.status = 'completed'
        etb1.planned_date = date(2025, 11, 15)
        etb1.actual_date = date(2025, 11, 18)
        etb1.build_qty = 10
        etb1.qty_produced = 10
        etb1.customer_approval = 'approved'
        etb1.approval_notes = 'Minor rework on 1 unit accepted'
        etb1.save()

        ps1 = BuildStage.objects.get(project=p1, name='PS')
        ps1.status = 'in-progress'
        ps1.planned_date = date(2026, 2, 1)
        ps1.build_qty = 50
        ps1.notes = 'Blocked by long-lead IC shortage'
        ps1.save()

        fas1 = BuildStage.objects.get(project=p1, name='FAS')
        fas1.status = 'planned'
        fas1.planned_date = date(2026, 5, 1)
        fas1.build_qty = 200
        fas1.save()

        # Gate checklist items for ETB
        for i, label in enumerate([
            'BOM finalized', 'PCB gerber released', 'Stencil ordered',
            'Test plan approved', 'Components kitted',
        ]):
            GateChecklistItem.objects.create(stage=etb1, label=label, checked=True, sort_order=i)

        for i, label in enumerate([
            'BOM R2.0 finalized', 'Long-lead components ordered',
            'Test jig ready', 'Stencil ordered for PS',
        ]):
            GateChecklistItem.objects.create(stage=ps1, label=label, checked=i < 2, sort_order=i)

        # Tasks
        tasks_data = [
            ('Pre-req: Main PCBA', [
                ('PCB Production', 'Axis', 14, date(2025, 10, 1), date(2025, 10, 14), 'done', etb1, 'PCB vendor: ABC Corp'),
                ('Component Procurement', 'SVI', 21, date(2025, 10, 1), date(2025, 10, 21), 'done', etb1, 'Long-lead ICs 6 weeks'),
                ('Stencil Fabrication', 'SVI', 7, date(2025, 10, 7), date(2025, 10, 14), 'done', etb1, ''),
                ('SMT Assembly', 'SVI', 5, date(2025, 10, 22), date(2025, 10, 27), 'done', etb1, ''),
                ('AOI Inspection', 'SVI', 2, date(2025, 10, 27), date(2025, 10, 29), 'done', etb1, ''),
            ]),
            ('Pre-req: Sub PCBA', [
                ('Sub PCB Production', 'Axis', 10, date(2025, 10, 5), date(2025, 10, 15), 'done', etb1, ''),
                ('Sub SMT Assembly', 'SVI', 3, date(2025, 10, 16), date(2025, 10, 19), 'done', etb1, ''),
            ]),
            ('Testing & Validation', [
                ('ICT Test Development', 'SVI', 10, date(2025, 10, 15), date(2025, 10, 25), 'done', etb1, ''),
                ('Functional Test', 'SVI', 5, date(2025, 10, 30), date(2025, 11, 4), 'done', etb1, ''),
                ('Burn-in Test', 'SVI', 3, date(2025, 11, 5), date(2025, 11, 8), 'done', etb1, ''),
                ('EMC Pre-compliance', 'External lab', 5, date(2025, 11, 10), date(2025, 11, 15), 'done', etb1, ''),
            ]),
            ('PS Build Preparation', [
                ('BOM R2.0 Review', 'Ekaluk', 5, date(2025, 12, 1), date(2025, 12, 5), 'done', ps1, 'Updated from ETB learnings'),
                ('Long-lead IC Ordering', 'SVI', 42, date(2025, 12, 5), date(2026, 1, 15), 'blocked', ps1, 'IC shortage — 6wk lead extended to 10wk'),
                ('PS Stencil Order', 'SVI', 7, date(2025, 12, 10), date(2025, 12, 17), 'done', ps1, ''),
                ('Test Jig Modification', 'SVI', 14, date(2025, 12, 15), date(2025, 12, 29), 'inprogress', ps1, ''),
                ('PS PCB Production', 'Axis', 14, date(2026, 1, 5), date(2026, 1, 19), 'open', ps1, ''),
                ('PS SMT Assembly', 'SVI', 7, date(2026, 1, 20), date(2026, 1, 27), 'open', ps1, ''),
            ]),
            ('Mechanical & Enclosure', [
                ('Enclosure Tooling', 'Tooling vendor', 30, date(2025, 11, 1), date(2025, 12, 1), 'done', etb1, ''),
                ('Enclosure First Samples', 'Tooling vendor', 14, date(2025, 12, 1), date(2025, 12, 15), 'done', etb1, ''),
            ]),
            ('FAS Preparation', [
                ('Production Line Setup', 'SVI', 14, date(2026, 4, 1), date(2026, 4, 15), 'open', fas1, ''),
                ('Mass Production BOM Freeze', 'Ekaluk', 3, date(2026, 4, 15), date(2026, 4, 18), 'open', fas1, ''),
                ('FAS Build Execution', 'SVI', 14, date(2026, 5, 1), date(2026, 5, 15), 'open', fas1, ''),
                ('Customer Sample Shipment', 'SVI', 5, date(2026, 5, 15), date(2026, 5, 20), 'open', fas1, ''),
            ]),
            ('Certification', [
                ('FCC Certification', 'Test lab', 21, date(2026, 3, 1), date(2026, 3, 22), 'open', fas1, ''),
            ]),
        ]
        order = 0
        task_map = {}
        for ms_name, items in tasks_data:
            ms_obj, _ = Milestone.objects.get_or_create(project=p1, name=ms_name, defaults={'sort_order': order})
            for name, who, days, start, end, status, stage, remark in items:
                t = Task.objects.create(
                    project=p1, name=name, milestone=ms_obj, who=who, days=days,
                    start=start, end=end, status=status, stage=stage, remark=remark,
                    sort_order=order,
                )
                task_map[name] = t
                order += 1

        # Issues
        i1 = Issue.objects.create(
            project=p1, title='Long-lead IC shortage delays PS build',
            desc='Key IC (U3) has 10-week lead time instead of expected 6 weeks. PS build date at risk.',
            severity='critical', status='open', owner='Ekaluk',
            due=date(2026, 1, 15), impact='PS build delayed by 4 weeks',
            stage=ps1,
        )
        if 'Long-lead IC Ordering' in task_map:
            i1.linked_tasks.add(task_map['Long-lead IC Ordering'])

        Issue.objects.create(
            project=p1, title='AOI false rejection rate high',
            desc='AOI rejecting 15% of boards on QFN package. Need to tune inspection parameters.',
            severity='high', status='investigating', owner='SVI QA',
            due=date(2025, 12, 20), impact='May slow PS throughput',
            stage=etb1,
        )

        Issue.objects.create(
            project=p1, title='Enclosure color mismatch on first samples',
            desc='RAL color slightly off on first tooling samples. Vendor adjusting.',
            severity='medium', status='resolved', owner='Tooling vendor',
            stage=etb1,
        )

        # Team
        TeamMember.objects.create(project=p1, name='Ekaluk Suwan', role='PGM', company='SVI Thailand', email='ekaluk@svi.co.th', phone='+66-81-234-5678')
        TeamMember.objects.create(project=p1, name='Lars Jensen', role='Customer PM', company='Axis Communications', email='lars.jensen@axis.com')
        TeamMember.objects.create(project=p1, name='Somchai Krit', role='PCB Engineer', company='SVI Thailand', email='somchai@svi.co.th')
        TeamMember.objects.create(project=p1, name='Pranee Rat', role='Test Engineer', company='SVI Thailand', email='pranee@svi.co.th')
        TeamMember.objects.create(project=p1, name='David Chen', role='Component Engineer', company='SVI Thailand')

        # NRE Items
        NREItem.objects.create(project=p1, category='Stencil', desc='Top-side stencil for Main PCBA', supplier='SVI', cost=8500, qty=1, po_status='po-received', po_number='AX-2025-0123', stage=etb1)
        NREItem.objects.create(project=p1, category='Stencil', desc='Bottom-side stencil for Main PCBA', supplier='SVI', cost=8500, qty=1, po_status='po-received', po_number='AX-2025-0123', stage=etb1)
        NREItem.objects.create(project=p1, category='Test Fixture', desc='ICT test fixture', supplier='SVI', cost=45000, qty=1, po_status='po-received', po_number='AX-2025-0124', stage=etb1)
        NREItem.objects.create(project=p1, category='Test Fixture', desc='Functional test fixture', supplier='SVI', cost=35000, qty=1, po_status='po-requested', stage=etb1)
        NREItem.objects.create(project=p1, category='Jig Fixture', desc='Assembly jig for Main PCBA', supplier='SVI', cost=15000, qty=2, po_status='no-po', due=date(2026, 1, 1), stage=ps1)
        NREItem.objects.create(project=p1, category='Tooling', desc='Enclosure injection mold', supplier='Tooling vendor', cost=180000, qty=1, po_status='paid', po_number='AX-2025-0100', stage=etb1)
        NREItem.objects.create(project=p1, category='Programming Fixture', desc='MCU programming jig', supplier='SVI', cost=12000, qty=1, po_status='no-po', due=date(2026, 1, 15), stage=ps1)
        NREItem.objects.create(project=p1, category='Pallet', desc='SMT production pallet', supplier='SVI', cost=25000, qty=2, po_status='no-po', due=date(2026, 3, 1), stage=fas1)

        # ── Project 2: Voltaren ──────────────────────────────────────
        p2 = Project.objects.create(
            name='Voltaren', pgm=u_natthida, customer=c_hanwha,
            start_date=date(2026, 1, 1), end_date=date(2026, 9, 30),
            color='#f59e0b', annual_volume=20000, annual_revenue=12000000, currency='THB',
        )
        p2.create_default_stages()

        etb2 = BuildStage.objects.get(project=p2, name='ETB')
        etb2.status = 'planned'
        etb2.planned_date = date(2026, 3, 15)
        etb2.build_qty = 5
        etb2.notes = 'Blocked by BOM approval'
        etb2.save()

        ps2 = BuildStage.objects.get(project=p2, name='PS')
        ps2.planned_date = date(2026, 6, 1)
        ps2.build_qty = 20
        ps2.save()

        fas2 = BuildStage.objects.get(project=p2, name='FAS')
        fas2.planned_date = date(2026, 8, 15)
        fas2.build_qty = 100
        fas2.save()

        GateChecklistItem.objects.create(stage=etb2, label='BOM approved by customer', checked=False, sort_order=0)
        GateChecklistItem.objects.create(stage=etb2, label='Schematic review complete', checked=True, sort_order=1)

        v_tasks = [
            ('Design & Planning', [
                ('Schematic Review', 'Natthida', 7, date(2026, 1, 5), date(2026, 1, 12), 'done', etb2, ''),
                ('BOM Creation', 'Natthida', 10, date(2026, 1, 12), date(2026, 1, 22), 'inprogress', etb2, 'Waiting customer approval'),
                ('PCB Layout', 'External', 14, date(2026, 1, 22), date(2026, 2, 5), 'open', etb2, ''),
            ]),
            ('Procurement', [
                ('Long-lead Components', 'SVI', 35, date(2026, 2, 1), date(2026, 3, 7), 'open', etb2, ''),
                ('PCB Fabrication', 'PCB vendor', 14, date(2026, 2, 10), date(2026, 2, 24), 'open', etb2, ''),
            ]),
            ('Build & Test', [
                ('ETB SMT Assembly', 'SVI', 5, date(2026, 3, 10), date(2026, 3, 15), 'open', etb2, ''),
                ('Functional Validation', 'SVI', 7, date(2026, 3, 15), date(2026, 3, 22), 'open', etb2, ''),
                ('Customer Review', 'Hanwha', 14, date(2026, 3, 22), date(2026, 4, 5), 'open', etb2, ''),
            ]),
        ]
        order = 0
        for ms_name, items in v_tasks:
            ms_obj, _ = Milestone.objects.get_or_create(project=p2, name=ms_name, defaults={'sort_order': order})
            for name, who, days, start, end, status, stage, remark in items:
                Task.objects.create(
                    project=p2, name=name, milestone=ms_obj, who=who, days=days,
                    start=start, end=end, status=status, stage=stage, remark=remark,
                    sort_order=order,
                )
                order += 1

        Issue.objects.create(
            project=p2, title='BOM approval pending from Hanwha',
            desc='Customer has not approved final BOM. ETB timeline depends on this.',
            severity='high', status='open', owner='Natthida',
            due=date(2026, 1, 30), impact='ETB build blocked until BOM approved',
            stage=etb2,
        )

        TeamMember.objects.create(project=p2, name='Natthida Pong', role='PGM', company='SVI Thailand', email='natthida@svi.co.th')
        TeamMember.objects.create(project=p2, name='Kim Sung', role='Customer PM', company='Hanwha', email='kim.sung@hanwha.com')

        NREItem.objects.create(project=p2, category='Stencil', desc='Main PCBA stencil set', supplier='SVI', cost=17000, qty=1, po_status='no-po', due=date(2026, 2, 15), stage=etb2)
        NREItem.objects.create(project=p2, category='Test Fixture', desc='Test fixture for Voltaren', supplier='SVI', cost=55000, qty=1, po_status='no-po', due=date(2026, 3, 1), stage=etb2)
        NREItem.objects.create(project=p2, category='Jig Fixture', desc='Assembly jig', supplier='SVI', cost=18000, qty=1, po_status='no-po', stage=ps2)

        # ── Project 3: Sentinel ──────────────────────────────────────
        p3 = Project.objects.create(
            name='Sentinel', pgm=u_somchai, customer=c_bosch,
            start_date=date(2026, 3, 1), end_date=date(2026, 12, 31),
            color='#06b6d4', annual_volume=30000, annual_revenue=18000000, currency='THB',
        )
        p3.create_default_stages()

        etb3 = BuildStage.objects.get(project=p3, name='ETB')
        etb3.planned_date = date(2026, 6, 1)
        etb3.build_qty = 10
        etb3.save()

        ps3 = BuildStage.objects.get(project=p3, name='PS')
        ps3.planned_date = date(2026, 9, 1)
        ps3.build_qty = 50
        ps3.save()

        fas3 = BuildStage.objects.get(project=p3, name='FAS')
        fas3.planned_date = date(2026, 11, 15)
        fas3.build_qty = 200
        fas3.save()

        s_tasks = [
            ('Design Phase', [
                ('Requirements Analysis', 'Somchai', 14, date(2026, 3, 1), date(2026, 3, 15), 'inprogress', None, ''),
                ('Schematic Design', 'Somchai', 21, date(2026, 3, 15), date(2026, 4, 5), 'open', etb3, ''),
                ('PCB Layout Design', 'External', 21, date(2026, 4, 5), date(2026, 4, 26), 'open', etb3, ''),
            ]),
            ('Procurement & Build', [
                ('Component Sourcing', 'SVI', 28, date(2026, 4, 15), date(2026, 5, 13), 'open', etb3, ''),
                ('ETB Build', 'SVI', 10, date(2026, 5, 20), date(2026, 5, 30), 'open', etb3, ''),
            ]),
        ]
        order = 0
        for ms_name, items in s_tasks:
            ms_obj, _ = Milestone.objects.get_or_create(project=p3, name=ms_name, defaults={'sort_order': order})
            for name, who, days, start, end, status, stage, remark in items:
                Task.objects.create(
                    project=p3, name=name, milestone=ms_obj, who=who, days=days,
                    start=start, end=end, status=status, stage=stage, remark=remark,
                    sort_order=order,
                )
                order += 1

        TeamMember.objects.create(project=p3, name='Somchai Krit', role='PGM', company='SVI Thailand', email='somchai@svi.co.th')
        TeamMember.objects.create(project=p3, name='Hans Mueller', role='Customer PM', company='Bosch', email='hans.mueller@bosch.com')

        NREItem.objects.create(project=p3, category='Stencil', desc='Sentinel PCBA stencil set', supplier='SVI', cost=17000, qty=1, po_status='no-po', stage=etb3)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded 3 projects: Greenland ({p1.tasks.count()} tasks, {p1.issues.count()} issues, {p1.nre_items.count()} NRE), '
            f'Voltaren ({p2.tasks.count()} tasks), Sentinel ({p3.tasks.count()} tasks)'
        ))
