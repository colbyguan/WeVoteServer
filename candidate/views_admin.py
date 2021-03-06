# candidate/views_admin.py
# Brought to you by We Vote. Be good.
# -*- coding: UTF-8 -*-

from .controllers import candidates_import_from_master_server, candidates_import_from_sample_file, \
    candidate_politician_match, find_duplicate_candidate, \
    retrieve_candidate_photos, retrieve_candidate_politician_match_options
from .models import CandidateCampaign, CandidateCampaignListManager, CandidateCampaignManager
from admin_tools.views import redirect_to_sign_in_page
from office.models import ContestOffice, ContestOfficeManager
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.messages import get_messages
from django.shortcuts import render
from election.models import Election, ElectionManager
from exception.models import handle_record_found_more_than_one_exception,\
    handle_record_not_found_exception, handle_record_not_saved_exception, print_to_log
from google_custom_search.models import GoogleSearchUser
from import_export_vote_smart.models import VoteSmartRatingOneCandidate
from import_export_vote_smart.votesmart_local import VotesmartApiError
from politician.models import PoliticianManager
from position.models import PositionEntered, PositionListManager
from twitter.models import TwitterLinkPossibility
from voter.models import voter_has_authority
import wevote_functions.admin
from wevote_functions.functions import convert_to_int, extract_twitter_handle_from_text_string, \
    positive_value_exists, STATE_CODE_MAP
from django.http import HttpResponse
import json


logger = wevote_functions.admin.get_logger(__name__)


# This page does not need to be protected.
# class CandidatesSyncOutView(APIView):
#     def get(self, request, format=None):
def candidates_sync_out_view(request):  # candidatesSyncOut
    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')
    candidate_search = request.GET.get('candidate_search', '')

    try:
        candidate_list = CandidateCampaign.objects.all()
        if positive_value_exists(google_civic_election_id):
            candidate_list = candidate_list.filter(google_civic_election_id=google_civic_election_id)
        if positive_value_exists(state_code):
            candidate_list = candidate_list.filter(state_code__iexact=state_code)
        filters = []
        if positive_value_exists(candidate_search):
            new_filter = Q(candidate_name__icontains=candidate_search)
            filters.append(new_filter)

            new_filter = Q(candidate_twitter_handle__icontains=candidate_search)
            filters.append(new_filter)

            new_filter = Q(candidate_url__icontains=candidate_search)
            filters.append(new_filter)

            new_filter = Q(party__icontains=candidate_search)
            filters.append(new_filter)

            new_filter = Q(we_vote_id__icontains=candidate_search)
            filters.append(new_filter)

            # Add the first query
            if len(filters):
                final_filters = filters.pop()

                # ...and "OR" the remaining items in the list
                for item in filters:
                    final_filters |= item

                candidate_list = candidate_list.filter(final_filters)

        candidate_list_dict = candidate_list.values('we_vote_id', 'maplight_id', 'vote_smart_id', 'contest_office_name',
                                                    'contest_office_we_vote_id', 'politician_we_vote_id',
                                                    'candidate_name', 'google_civic_candidate_name', 'party',
                                                    'photo_url', 'photo_url_from_maplight',
                                                    'photo_url_from_vote_smart', 'order_on_ballot',
                                                    'google_civic_election_id', 'ocd_division_id', 'state_code',
                                                    'candidate_url', 'facebook_url', 'twitter_url',
                                                    'twitter_user_id', 'candidate_twitter_handle', 'twitter_name',
                                                    'twitter_location', 'twitter_followers_count',
                                                    'twitter_profile_image_url_https', 'twitter_description',
                                                    'google_plus_url', 'youtube_url', 'candidate_email',
                                                    'candidate_phone', 'wikipedia_page_id', 'wikipedia_page_title',
                                                    'wikipedia_photo_url', 'ballotpedia_page_title',
                                                    'ballotpedia_photo_url', 'ballot_guide_official_statement')
        if candidate_list_dict:
            candidate_list_json = list(candidate_list_dict)
            return HttpResponse(json.dumps(candidate_list_json), content_type='application/json')
    except Exception as e:
        pass

    json_data = {
        'success': False,
        'status': 'CANDIDATE_LIST_MISSING'
    }
    return HttpResponse(json.dumps(json_data), content_type='application/json')


@login_required
def candidates_import_from_master_server_view(request):
    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    state_code = request.GET.get('state_code', '')

    results = candidates_import_from_master_server(request, google_civic_election_id, state_code)

    if not results['success']:
        messages.add_message(request, messages.ERROR, results['status'])
    else:
        messages.add_message(request, messages.INFO, 'Candidates import completed. '
                                                     'Saved: {saved}, Updated: {updated}, '
                                                     'Duplicates skipped: '
                                                     '{duplicates_removed}, '
                                                     'Not processed: {not_processed}'
                                                     ''.format(saved=results['saved'],
                                                               updated=results['updated'],
                                                               duplicates_removed=results['duplicates_removed'],
                                                               not_processed=results['not_processed']))
    return HttpResponseRedirect(reverse('admin_tools:sync_dashboard', args=()) + "?google_civic_election_id=" +
                                str(google_civic_election_id) + "&state_code=" + str(state_code))


@login_required
def candidates_import_from_sample_file_view(request):
    """
    This gives us sample organizations, candidate campaigns, and positions for testing
    :return:
    """
    authority_required = {'admin'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    # We are importing candidate_campaigns data (and not politician data) because all we are doing is making sure we
    #  sync to the same We Vote ID. This is critical so we can link Positions to Organization & Candidate Campaign.
    # At this point (June 2015) we assume the politicians have been imported from Google Civic. We aren't assigning
    # the politicians a We Vote id, but instead use their full name as the identifier
    candidates_import_from_sample_file(request, False)

    messages.add_message(request, messages.INFO, 'Candidates imported.')

    return HttpResponseRedirect(reverse('import_export:import_export_index', args=()))


@login_required
def candidate_list_view(request):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = convert_to_int(request.GET.get('google_civic_election_id', 0))
    candidate_search = request.GET.get('candidate_search', '')
    state_code = request.GET.get('state_code', '')
    show_all = request.GET.get('show_all', False)

    state_list = STATE_CODE_MAP
    sorted_state_list = sorted(state_list.items())

    candidate_list = []
    candidate_list_count = 0

    try:
        candidate_list = CandidateCampaign.objects.all()
        if positive_value_exists(google_civic_election_id):
            candidate_list = candidate_list.filter(google_civic_election_id=google_civic_election_id)
        if positive_value_exists(state_code):
            candidate_list = candidate_list.filter(state_code__iexact=state_code)

        if positive_value_exists(candidate_search):
            search_words = candidate_search.split()
            for one_word in search_words:
                filters = []

                new_filter = Q(candidate_name__icontains=one_word)
                filters.append(new_filter)

                new_filter = Q(candidate_twitter_handle__icontains=one_word)
                filters.append(new_filter)

                new_filter = Q(candidate_url__icontains=one_word)
                filters.append(new_filter)

                new_filter = Q(party__icontains=one_word)
                filters.append(new_filter)

                new_filter = Q(we_vote_id__icontains=one_word)
                filters.append(new_filter)

                # Add the first query
                if len(filters):
                    final_filters = filters.pop()

                    # ...and "OR" the remaining items in the list
                    for item in filters:
                        final_filters |= item

                    candidate_list = candidate_list.filter(final_filters)
        candidate_list = candidate_list.order_by('candidate_name')
        candidate_list_count = candidate_list.count()

        if not positive_value_exists(show_all):
            candidate_list = candidate_list[:200]
    except CandidateCampaign.DoesNotExist:
        # This is fine, create new
        pass

    status_print_list = ""
    status_print_list += "candidate_list_count: " + \
                         str(candidate_list_count) + " "

    messages.add_message(request, messages.INFO, status_print_list)

    messages_on_stage = get_messages(request)

    election_list = Election.objects.order_by('-election_day_text')

    # Attach the best guess Twitter account, if any, to each candidate in list
    for candidate in candidate_list:
        try:
            twitter_possibility_query = TwitterLinkPossibility.objects.order_by('-likelihood_percentage')
            twitter_possibility_query = twitter_possibility_query.filter(
                candidate_campaign_we_vote_id=candidate.we_vote_id)
            candidate.candidate_merge_possibility = twitter_possibility_query[0]
        except Exception as e:
            candidate.candidate_merge_possibility = None

    template_values = {
        'messages_on_stage':        messages_on_stage,
        'candidate_list':           candidate_list,
        'candidate_search':         candidate_search,
        'election_list':            election_list,
        'state_code':               state_code,
        'state_list':               sorted_state_list,
        'google_civic_election_id': google_civic_election_id,
    }
    return render(request, 'candidate/candidate_list.html', template_values)


@login_required
def candidate_new_view(request):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    contest_office_id = request.GET.get('contest_office_id', 0)

    # These variables are here because there was an error on the edit_process_view and the voter needs to try again
    candidate_name = request.GET.get('candidate_name', "")
    google_civic_candidate_name = request.GET.get('google_civic_candidate_name', "")
    state_code = request.GET.get('state_code', "")
    candidate_twitter_handle = request.GET.get('candidate_twitter_handle', "")
    candidate_url = request.GET.get('candidate_url', "")
    party = request.GET.get('party', "")
    ballot_guide_official_statement = request.GET.get('ballot_guide_official_statement', "")
    vote_smart_id = request.GET.get('vote_smart_id', "")
    maplight_id = request.GET.get('maplight_id', "")
    politician_we_vote_id = request.GET.get('politician_we_vote_id', "")

    # These are the Offices already entered for this election
    try:
        contest_office_list = ContestOffice.objects.order_by('office_name')
        contest_office_list = contest_office_list.filter(google_civic_election_id=google_civic_election_id)
    except Exception as e:
        handle_record_not_found_exception(e, logger=logger)
        contest_office_list = []

    # Its helpful to see existing candidates when entering a new candidate
    candidate_list = []
    try:
        candidate_list = CandidateCampaign.objects.all()
        if positive_value_exists(google_civic_election_id):
            candidate_list = candidate_list.filter(google_civic_election_id=google_civic_election_id)
        if positive_value_exists(contest_office_id):
            candidate_list = candidate_list.filter(contest_office_id=contest_office_id)
        candidate_list = candidate_list.order_by('candidate_name')[:500]
    except CandidateCampaign.DoesNotExist:
        # This is fine, create new
        pass

    election_manager = ElectionManager()
    election_results = election_manager.retrieve_election(google_civic_election_id)
    state_code_from_election = ""
    if election_results['election_found']:
        election = election_results['election']
        election_found = election_results['election_found']
        state_code_from_election = election.get_election_state()

    messages_on_stage = get_messages(request)
    template_values = {
        'messages_on_stage':        messages_on_stage,
        'office_list':              contest_office_list,
        'contest_office_id':        contest_office_id,  # We need to always pass in separately for the template to work
        'google_civic_election_id': google_civic_election_id,
        'candidate_list':           candidate_list,
        'state_code_from_election': state_code_from_election,
        # Incoming variables, not saved yet
        'candidate_name':                   candidate_name,
        'google_civic_candidate_name':      google_civic_candidate_name,
        'state_code':                       state_code,
        'candidate_twitter_handle':         candidate_twitter_handle,
        'candidate_url':                    candidate_url,
        'party':                            party,
        'ballot_guide_official_statement':  ballot_guide_official_statement,
        'vote_smart_id':                    vote_smart_id,
        'maplight_id':                      maplight_id,
        'politician_we_vote_id':            politician_we_vote_id,
    }
    return render(request, 'candidate/candidate_edit.html', template_values)


@login_required
def candidate_edit_view(request, candidate_id=0, candidate_campaign_we_vote_id=""):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    # These variables are here because there was an error on the edit_process_view and the voter needs to try again
    candidate_name = request.GET.get('candidate_name', False)
    google_civic_candidate_name = request.GET.get('google_civic_candidate_name', False)
    candidate_twitter_handle = request.GET.get('candidate_twitter_handle', False)
    candidate_url = request.GET.get('candidate_url', False)
    party = request.GET.get('party', False)
    ballot_guide_official_statement = request.GET.get('ballot_guide_official_statement', False)
    vote_smart_id = request.GET.get('vote_smart_id', False)
    maplight_id = request.GET.get('maplight_id', False)
    state_code = request.GET.get('state_code', "")

    messages_on_stage = get_messages(request)
    candidate_id = convert_to_int(candidate_id)
    candidate_on_stage_found = False
    candidate_on_stage = CandidateCampaign()
    contest_office_id = 0
    google_civic_election_id = 0

    try:
        if positive_value_exists(candidate_id):
            candidate_on_stage = CandidateCampaign.objects.get(id=candidate_id)
        else:
            candidate_on_stage = CandidateCampaign.objects.get(we_vote_id=candidate_campaign_we_vote_id)
        candidate_on_stage_found = True
        candidate_id = candidate_on_stage.id
        contest_office_id = candidate_on_stage.contest_office_id
        google_civic_election_id = candidate_on_stage.google_civic_election_id
    except CandidateCampaign.MultipleObjectsReturned as e:
        handle_record_found_more_than_one_exception(e, logger=logger)
    except CandidateCampaign.DoesNotExist:
        # This is fine, create new below
        pass

    if candidate_on_stage_found:
        # Working with Vote Smart data
        try:
            vote_smart_candidate_id = candidate_on_stage.vote_smart_id
            rating_list_query = VoteSmartRatingOneCandidate.objects.order_by('-timeSpan')  # Desc order
            rating_list = rating_list_query.filter(candidateId=vote_smart_candidate_id)
        except VotesmartApiError as error_instance:
            # Catch the error message coming back from Vote Smart and pass it in the status
            error_message = error_instance.args
            status = "EXCEPTION_RAISED: {error_message}".format(error_message=error_message)
            print_to_log(logger=logger, exception_message_optional=status)
            rating_list = []

        # Working with We Vote Positions
        try:
            candidate_position_list = PositionEntered.objects.order_by('stance')
            candidate_position_list = candidate_position_list.filter(candidate_campaign_id=candidate_id)
            # if positive_value_exists(google_civic_election_id):
            #     organization_position_list = candidate_position_list.filter(
            #         google_civic_election_id=google_civic_election_id)
        except Exception as e:
            handle_record_not_found_exception(e, logger=logger)
            candidate_position_list = []

        # Working with Offices for this election
        try:
            contest_office_list = ContestOffice.objects.order_by('office_name')
            contest_office_list = contest_office_list.filter(
                google_civic_election_id=candidate_on_stage.google_civic_election_id)
        except Exception as e:
            handle_record_not_found_exception(e, logger=logger)
            contest_office_list = []

        # Was a candidate_merge_possibility_found?
        candidate_on_stage.candidate_merge_possibility_found = True  # TODO DALE Make dynamic

        twitter_link_possibility_list = []
        try:
            twitter_possibility_query = TwitterLinkPossibility.objects.order_by('-likelihood_percentage')
            twitter_possibility_query = twitter_possibility_query.filter(
                candidate_campaign_we_vote_id=candidate_on_stage.we_vote_id)
            twitter_link_possibility_list = list(twitter_possibility_query)
        except Exception as e:
            pass

        google_search_possibility_list = []
        try:
            google_search_possibility_query = GoogleSearchUser.objects.order_by('-likelihood_score')
            google_search_possibility_query = google_search_possibility_query.filter(
                candidate_campaign_we_vote_id=candidate_on_stage.we_vote_id)
            google_search_possibility_list = list(google_search_possibility_query)

        except Exception as e:
            pass

        template_values = {
            'messages_on_stage':                messages_on_stage,
            'candidate':                        candidate_on_stage,
            'rating_list':                      rating_list,
            'candidate_position_list':          candidate_position_list,
            'office_list':                      contest_office_list,
            'contest_office_id':                contest_office_id,
            'google_civic_election_id':         google_civic_election_id,
            'state_code':                       state_code,
            'twitter_link_possibility_list':    twitter_link_possibility_list,
            'google_search_possibility_list':   google_search_possibility_list,
            # Incoming variables, not saved yet
            'candidate_name':                   candidate_name,
            'google_civic_candidate_name':      google_civic_candidate_name,
            'candidate_twitter_handle':         candidate_twitter_handle,
            'candidate_url':                    candidate_url,
            'party':                            party,
            'ballot_guide_official_statement':  ballot_guide_official_statement,
            'vote_smart_id':                    vote_smart_id,
            'maplight_id':                      maplight_id,
        }
    else:
        template_values = {
            'messages_on_stage':    messages_on_stage,
            # Incoming variables
            'vote_smart_id':        vote_smart_id,
        }
    return render(request, 'candidate/candidate_edit.html', template_values)


@login_required
def candidate_edit_process_view(request):
    """
    Process the new or edit candidate forms
    :param request:
    :return:
    """
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    look_for_politician = request.POST.get('look_for_politician', False)  # If this comes in with value, don't save
    remove_duplicate_process = request.POST.get('remove_duplicate_process', False)

    candidate_id = convert_to_int(request.POST['candidate_id'])
    candidate_name = request.POST.get('candidate_name', False)
    google_civic_candidate_name = request.POST.get('google_civic_candidate_name', False)
    google_civic_election_id = request.POST.get('google_civic_election_id', 0)
    candidate_twitter_handle = request.POST.get('candidate_twitter_handle', False)
    if positive_value_exists(candidate_twitter_handle):
        candidate_twitter_handle = extract_twitter_handle_from_text_string(candidate_twitter_handle)
    candidate_url = request.POST.get('candidate_url', False)
    contest_office_id = request.POST.get('contest_office_id', False)
    ballot_guide_official_statement = request.POST.get('ballot_guide_official_statement', False)
    party = request.POST.get('party', False)
    vote_smart_id = request.POST.get('vote_smart_id', False)
    maplight_id = request.POST.get('maplight_id', False)
    state_code = request.POST.get('state_code', False)
    politician_we_vote_id = request.POST.get('politician_we_vote_id', False)

    # Check to see if this candidate is already being used anywhere
    candidate_on_stage_found = False
    candidate_on_stage = CandidateCampaign()
    if positive_value_exists(candidate_id):
        try:
            candidate_query = CandidateCampaign.objects.filter(id=candidate_id)
            if len(candidate_query):
                candidate_on_stage = candidate_query[0]
                candidate_on_stage_found = True
        except Exception as e:
            pass

    # If linked to a Politician, make sure that both politician_id and politician_we_vote_id exist
    if candidate_on_stage_found:
        if positive_value_exists(candidate_on_stage.politician_we_vote_id) \
                and not positive_value_exists(candidate_on_stage.politician_id):
            try:
                politician_manager = PoliticianManager()
                results = politician_manager.retrieve_politician(0, candidate_on_stage.politician_we_vote_id)
                if results['politician_found']:
                    politician = results['politician']
                    candidate_on_stage.politician_id = politician.id
                    candidate_on_stage.save()
                pass
            except Exception as e:
                messages.add_message(request, messages.ERROR, 'Could not save candidate.')

    contest_office_we_vote_id = ''
    contest_office_name = ''
    if positive_value_exists(contest_office_id):
        contest_office_manager = ContestOfficeManager()
        results = contest_office_manager.retrieve_contest_office_from_id(contest_office_id)
        if results['contest_office_found']:
            contest_office = results['contest_office']
            contest_office_we_vote_id = contest_office.we_vote_id
            contest_office_name = contest_office.office_name

    election_manager = ElectionManager()
    election_results = election_manager.retrieve_election(google_civic_election_id)
    state_code_from_election = ""
    if election_results['election_found']:
        election = election_results['election']
        election_found = election_results['election_found']
        state_code_from_election = election.get_election_state()

    best_state_code = state_code_from_election if positive_value_exists(state_code_from_election) \
        else state_code

    if positive_value_exists(look_for_politician):
        # If here, we specifically want to see if a politician exists, given the information submitted
        match_results = retrieve_candidate_politician_match_options(vote_smart_id, maplight_id,
                                                                    candidate_twitter_handle,
                                                                    candidate_name, best_state_code)
        if match_results['politician_found']:
            messages.add_message(request, messages.INFO, 'Politician found! Information filled into this form.')
            matching_politician = match_results['politician']
            politician_we_vote_id = matching_politician.we_vote_id
            politician_twitter_handle = matching_politician.politician_twitter_handle \
                if positive_value_exists(matching_politician.politician_twitter_handle) else ""
            # If Twitter handle was entered in the Add new form, leave in place. Otherwise, pull from Politician entry.
            candidate_twitter_handle = candidate_twitter_handle if candidate_twitter_handle \
                else politician_twitter_handle
            vote_smart_id = matching_politician.vote_smart_id
            maplight_id = matching_politician.maplight_id if positive_value_exists(matching_politician.maplight_id) \
                else ""
            party = matching_politician.political_party
            google_civic_candidate_name = matching_politician.google_civic_candidate_name
            candidate_name = candidate_name if positive_value_exists(candidate_name) \
                else matching_politician.politician_name
        else:
            messages.add_message(request, messages.INFO, 'No politician found. Please make sure you have entered '
                                                         '1) Candidate Name & State Code, '
                                                         '2) Twitter Handle, or '
                                                         '3) Vote Smart Id')

        url_variables = "?google_civic_election_id=" + str(google_civic_election_id) + \
                        "&candidate_name=" + str(candidate_name) + \
                        "&state_code=" + str(state_code) + \
                        "&google_civic_candidate_name=" + str(google_civic_candidate_name) + \
                        "&contest_office_id=" + str(contest_office_id) + \
                        "&candidate_twitter_handle=" + str(candidate_twitter_handle) + \
                        "&candidate_url=" + str(candidate_url) + \
                        "&party=" + str(party) + \
                        "&ballot_guide_official_statement=" + str(ballot_guide_official_statement) + \
                        "&vote_smart_id=" + str(vote_smart_id) + \
                        "&politician_we_vote_id=" + str(politician_we_vote_id) + \
                        "&maplight_id=" + str(maplight_id)

        if positive_value_exists(candidate_id):
            return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)) + url_variables)
        else:
            return HttpResponseRedirect(reverse('candidate:candidate_new', args=()) + url_variables)

    # Check to see if there is a duplicate candidate already saved for this election
    existing_candidate_found = False
    if not positive_value_exists(candidate_id):
        try:
            filter_list = Q()

            at_least_one_filter = False
            if positive_value_exists(vote_smart_id):
                at_least_one_filter = True
                filter_list |= Q(vote_smart_id=vote_smart_id)
            if positive_value_exists(maplight_id):
                at_least_one_filter = True
                filter_list |= Q(maplight_id=maplight_id)

            if at_least_one_filter:
                candidate_duplicates_query = CandidateCampaign.objects.filter(filter_list)
                candidate_duplicates_query = candidate_duplicates_query.filter(
                    google_civic_election_id=google_civic_election_id)

                if len(candidate_duplicates_query):
                    existing_candidate_found = True
        except Exception as e:
            pass

    try:
        if existing_candidate_found:
            # We have found a duplicate for this election
            messages.add_message(request, messages.ERROR, 'This candidate is already saved for this election.')
            url_variables = "?google_civic_election_id=" + str(google_civic_election_id) + \
                            "&candidate_name=" + str(candidate_name) + \
                            "&state_code=" + str(state_code) + \
                            "&google_civic_candidate_name=" + str(google_civic_candidate_name) + \
                            "&contest_office_id=" + str(contest_office_id) + \
                            "&candidate_twitter_handle=" + str(candidate_twitter_handle) + \
                            "&candidate_url=" + str(candidate_url) + \
                            "&party=" + str(party) + \
                            "&ballot_guide_official_statement=" + str(ballot_guide_official_statement) + \
                            "&vote_smart_id=" + str(vote_smart_id) + \
                            "&politician_we_vote_id=" + str(politician_we_vote_id) + \
                            "&maplight_id=" + str(maplight_id)
            return HttpResponseRedirect(reverse('candidate:candidate_new', args=()) + url_variables)
        elif candidate_on_stage_found:
            # Update
            if candidate_name is not False:
                candidate_on_stage.candidate_name = candidate_name
            if candidate_twitter_handle is not False:
                candidate_on_stage.candidate_twitter_handle = candidate_twitter_handle
            if candidate_url is not False:
                candidate_on_stage.candidate_url = candidate_url
            if ballot_guide_official_statement is not False:
                candidate_on_stage.ballot_guide_official_statement = ballot_guide_official_statement
            if party is not False:
                candidate_on_stage.party = party
            if google_civic_candidate_name is not False:
                candidate_on_stage.google_civic_candidate_name = google_civic_candidate_name

            # Check to see if this is a We Vote-created election
            # is_we_vote_google_civic_election_id = True \
            #     if convert_to_int(candidate_on_stage.google_civic_election_id) >= 1000000 \
            #     else False

            if contest_office_id is not False:
                # We only allow updating of candidates within the We Vote Admin in
                candidate_on_stage.contest_office_id = contest_office_id
                candidate_on_stage.contest_office_we_vote_id = contest_office_we_vote_id
                candidate_on_stage.contest_office_name = contest_office_name
            candidate_on_stage.save()

            # Now refresh the cache entries for this candidate

            messages.add_message(request, messages.INFO, 'Candidate Campaign updated.')
        else:
            # Create new
            # election must be found
            if not election_found:
                messages.add_message(request, messages.ERROR, 'Could not find election -- required to save candidate.')
                return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

            required_candidate_variables = True \
                if positive_value_exists(candidate_name) and positive_value_exists(contest_office_id) \
                else False
            if required_candidate_variables:
                candidate_on_stage = CandidateCampaign(
                    candidate_name=candidate_name,
                    google_civic_election_id=google_civic_election_id,
                    contest_office_id=contest_office_id,
                    contest_office_we_vote_id=contest_office_we_vote_id,
                    state_code=best_state_code,
                )
                if google_civic_candidate_name is not False:
                    candidate_on_stage.google_civic_candidate_name = google_civic_candidate_name
                if candidate_twitter_handle is not False:
                    candidate_on_stage.candidate_twitter_handle = candidate_twitter_handle
                if candidate_url is not False:
                    candidate_on_stage.candidate_url = candidate_url
                if party is not False:
                    candidate_on_stage.party = party
                if ballot_guide_official_statement is not False:
                    candidate_on_stage.ballot_guide_official_statement = ballot_guide_official_statement
                if vote_smart_id is not False:
                    candidate_on_stage.vote_smart_id = vote_smart_id
                if maplight_id is not False:
                    candidate_on_stage.maplight_id = maplight_id
                if politician_we_vote_id is not False:
                    candidate_on_stage.politician_we_vote_id = politician_we_vote_id

                candidate_on_stage.save()
                candidate_id = candidate_on_stage.id
                messages.add_message(request, messages.INFO, 'New candidate saved.')
            else:
                # messages.add_message(request, messages.INFO, 'Could not save -- missing required variables.')
                url_variables = "?google_civic_election_id=" + str(google_civic_election_id) + \
                                "&candidate_name=" + str(candidate_name) + \
                                "&state_code=" + str(state_code) + \
                                "&google_civic_candidate_name=" + str(google_civic_candidate_name) + \
                                "&contest_office_id=" + str(contest_office_id) + \
                                "&candidate_twitter_handle=" + str(candidate_twitter_handle) + \
                                "&candidate_url=" + str(candidate_url) + \
                                "&party=" + str(party) + \
                                "&ballot_guide_official_statement=" + str(ballot_guide_official_statement) + \
                                "&vote_smart_id=" + str(vote_smart_id) + \
                                "&politician_we_vote_id=" + str(politician_we_vote_id) + \
                                "&maplight_id=" + str(maplight_id)
                if positive_value_exists(candidate_id):
                    return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)) +
                                                url_variables)
                else:
                    return HttpResponseRedirect(reverse('candidate:candidate_new', args=()) +
                                                url_variables)

    except Exception as e:
        messages.add_message(request, messages.ERROR, 'Could not save candidate.')
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

    if remove_duplicate_process:
        return HttpResponseRedirect(reverse('candidate:find_and_remove_duplicate_candidates', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id) +
                                    "&state_code=" + str(state_code))
    else:
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))


@login_required
def candidate_politician_match_view(request):
    """
    Try to match the current candidate to an existing politician entry. If a politician entry isn't found,
    create an entry.
    :param request:
    :return:
    """
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_id = request.GET.get('candidate_id', 0)
    candidate_id = convert_to_int(candidate_id)
    # google_civic_election_id is included for interface usability reasons and isn't used in the processing
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    google_civic_election_id = convert_to_int(google_civic_election_id)

    if not positive_value_exists(candidate_id):
        messages.add_message(request, messages.ERROR, "The candidate_id variable was not passed in.")
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

    candidate_campaign_manager = CandidateCampaignManager()

    results = candidate_campaign_manager.retrieve_candidate_campaign_from_id(candidate_id)
    if not positive_value_exists(results['candidate_campaign_found']):
        messages.add_message(request, messages.ERROR,
                             "Candidate '{candidate_id}' not found.".format(candidate_id=candidate_id))
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

    we_vote_candidate = results['candidate_campaign']

    # Make sure we have a politician for this candidate. If we don't, create a politician entry, and save the
    # politician_we_vote_id in the candidate
    results = candidate_politician_match(we_vote_candidate)

    display_messages = True
    if results['status'] and display_messages:
        messages.add_message(request, messages.INFO, results['status'])
    return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)) +
                                "?google_civic_election_id=" + str(google_civic_election_id))


@login_required
def candidate_politician_match_for_this_election_view(request):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_list = []
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    google_civic_election_id = convert_to_int(google_civic_election_id)

    # We only want to process if a google_civic_election_id comes in
    if not positive_value_exists(google_civic_election_id):
        messages.add_message(request, messages.ERROR, "Google Civic Election ID required.")
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()))

    try:
        candidate_list = CandidateCampaign.objects.order_by('candidate_name')
        candidate_list = candidate_list.filter(google_civic_election_id=google_civic_election_id)
    except CandidateCampaign.DoesNotExist:
        messages.add_message(request, messages.INFO, "No candidates found for this election: {id}.".format(
            id=google_civic_election_id))
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) + "?google_civic_election_id={var}"
                                                                                   "".format(
                                                                                   var=google_civic_election_id))

    num_candidates_reviewed = 0
    num_that_already_have_politician_we_vote_id = 0
    new_politician_created = 0
    existing_politician_found = 0
    multiple_politicians_found = 0
    other_results = 0

    message = "About to loop through all of the candidates in this election to make sure we have a politician record."
    print_to_log(logger, exception_message_optional=message)

    # Loop through all of the candidates in this election
    for we_vote_candidate in candidate_list:
        num_candidates_reviewed += 1
        match_results = candidate_politician_match(we_vote_candidate)
        if we_vote_candidate.politician_we_vote_id:
            num_that_already_have_politician_we_vote_id += 1
        elif match_results['politician_created']:
            new_politician_created += 1
        elif match_results['politician_found']:
            existing_politician_found += 1
        elif match_results['politician_list_found']:
            multiple_politicians_found += 1
        else:
            other_results += 1

    message = "Google Civic Election ID: {election_id}, " \
              "{num_candidates_reviewed} candidates reviewed, " \
              "{num_that_already_have_politician_we_vote_id} Candidates that already have Politician Ids, " \
              "{new_politician_created} politicians just created, " \
              "{existing_politician_found} politicians found that already exist, " \
              "{multiple_politicians_found} times we found multiple politicians and could not link, " \
              "{other_results} other results". \
              format(election_id=google_civic_election_id,
                     num_candidates_reviewed=num_candidates_reviewed,
                     num_that_already_have_politician_we_vote_id=num_that_already_have_politician_we_vote_id,
                     new_politician_created=new_politician_created,
                     existing_politician_found=existing_politician_found,
                     multiple_politicians_found=multiple_politicians_found,
                     other_results=other_results)

    print_to_log(logger, exception_message_optional=message)
    messages.add_message(request, messages.INFO, message)

    return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) + "?google_civic_election_id={var}".format(
        var=google_civic_election_id))


@login_required
def candidate_retrieve_photos_view(request, candidate_id):
    authority_required = {'admin'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_id = convert_to_int(candidate_id)
    force_retrieve = request.GET.get('force_retrieve', 0)

    candidate_campaign_manager = CandidateCampaignManager()

    results = candidate_campaign_manager.retrieve_candidate_campaign_from_id(candidate_id)
    if not positive_value_exists(results['candidate_campaign_found']):
        messages.add_message(request, messages.ERROR,
                             "Candidate '{candidate_id}' not found.".format(candidate_id=candidate_id))
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

    we_vote_candidate = results['candidate_campaign']

    display_messages = True
    retrieve_candidate_results = retrieve_candidate_photos(we_vote_candidate, force_retrieve)

    if retrieve_candidate_results['status'] and display_messages:
        messages.add_message(request, messages.INFO, retrieve_candidate_results['status'])
    return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))


@login_required
def find_and_remove_duplicate_candidates_view(request):
    authority_required = {'admin'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_list = []
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    google_civic_election_id = convert_to_int(google_civic_election_id)

    number_of_duplicate_candidates_processed = 0
    number_of_duplicate_candidates_failed = 0
    number_of_duplicates_could_not_process = 0

    # We only want to process if a google_civic_election_id comes in
    if not positive_value_exists(google_civic_election_id):
        messages.add_message(request, messages.ERROR, "Google Civic Election ID required.")
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()))

    try:
        # We sort by ID so that the entry which was saved first becomes the "master"
        candidate_list = CandidateCampaign.objects.order_by('id')
        candidate_list = candidate_list.filter(google_civic_election_id=google_civic_election_id)
    except CandidateCampaign.DoesNotExist:
        pass

    # Loop through all of the candidates in this election
    for we_vote_candidate in candidate_list:
        results = find_duplicate_candidate(we_vote_candidate)

        # If we find candidates to merge, stop and ask for confirmation
        if results['candidate_merge_possibility_found']:
            messages_on_stage = get_messages(request)
            template_values = {
                'messages_on_stage': messages_on_stage,
                'candidate_option1': we_vote_candidate,
                'candidate_option2': results['candidate_merge_possibility'],
            }
            return render(request, 'candidate/candidate_merge.html', template_values)

    # message = "Google Civic Election ID: {election_id}, " \
    #           "{number_of_duplicate_candidates_processed} duplicates processed, " \
    #           "{number_of_duplicate_candidates_failed} duplicate merges failed, " \
    #           "{number_of_duplicates_could_not_process} could not be processed because 3 exist " \
    #           "".format(election_id=google_civic_election_id,
    #                     number_of_duplicate_candidates_processed=number_of_duplicate_candidates_processed,
    #                     number_of_duplicate_candidates_failed=number_of_duplicate_candidates_failed,
    #                     number_of_duplicates_could_not_process=number_of_duplicates_could_not_process)

    # messages.add_message(request, messages.INFO, message)

    return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) + "?google_civic_election_id={var}".format(
        var=google_civic_election_id))


@login_required
def find_duplicate_candidate_view(request, candidate_id):
    authority_required = {'admin'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_list = []

    number_of_duplicate_candidates_processed = 0
    number_of_duplicate_candidates_failed = 0
    number_of_duplicates_could_not_process = 0

    google_civic_election_id = 0

    candidate_manager = CandidateCampaignManager()
    candidate_results = candidate_manager.retrieve_candidate_campaign_from_id(candidate_id)
    if not candidate_results['candidate_campaign_found']:
        messages.add_message(request, messages.ERROR, "Candidate not found.")
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id))

    candidate = candidate_results['candidate_campaign']

    if not positive_value_exists(google_civic_election_id):
        messages.add_message(request, messages.ERROR, "Candidate must have an election_id in order to merge.")
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

    results = find_duplicate_candidate(candidate)

    if results['candidate_merge_possibility_found']:
        # If we find candidates to merge, ask for confirmation
        messages_on_stage = get_messages(request)
        template_values = {
            'messages_on_stage': messages_on_stage,
            'candidate_option1': candidate,
            'candidate_option2': results['candidate_merge_possibility'],
        }
        return render(request, 'candidate/candidate_merge.html', template_values)

    # # If we can automatically merge, we should do it
    # is_automatic_merge_ok_results = candidate_campaign_list_manager.is_automatic_merge_ok(
    #     we_vote_candidate, candidate_duplicate_list[0])
    # if is_automatic_merge_ok_results['automatic_merge_ok']:
    #     automatic_merge_results = candidate_campaign_list_manager.do_automatic_merge(
    #         we_vote_candidate, candidate_duplicate_list[0])
    #     if automatic_merge_results['success']:
    #         number_of_duplicate_candidates_processed += 1
    #     else:
    #         number_of_duplicate_candidates_failed += 1
    # else:
    #     # If we cannot automatically merge, direct to a page where we can look at the two side-by-side
    #     message = "Google Civic Election ID: {election_id}, " \
    #               "{num_of_duplicate_candidates_processed} duplicates processed, " \
    #               "{number_of_duplicate_candidates_failed} duplicate merges failed, " \
    #               "{number_of_duplicates_could_not_process} could not be processed because 3 exist " \
    #               "".format(election_id=google_civic_election_id,
    #                         num_of_duplicate_candidates_processed=number_of_duplicate_candidates_processed,
    #                         number_of_duplicate_candidates_failed=number_of_duplicate_candidates_failed,
    #                         number_of_duplicates_could_not_process=number_of_duplicates_could_not_process)
    #
    #     messages.add_message(request, messages.INFO, message)
    #
    #     message = "{is_automatic_merge_ok_results_status} " \
    #               "".format(is_automatic_merge_ok_results_status=is_automatic_merge_ok_results['status'])
    #     messages.add_message(request, messages.ERROR, message)
    #
    #     messages_on_stage = get_messages(request)
    #     template_values = {
    #         'messages_on_stage': messages_on_stage,
    #         'candidate_option1': we_vote_candidate,
    #         'candidate_option2': candidate_duplicate_list[0],
    #     }
    #     return render(request, 'candidate/candidate_merge.html', template_values)

    message = "Google Civic Election ID: {election_id}, " \
              "{number_of_duplicate_candidates_processed} duplicates processed, " \
              "{number_of_duplicate_candidates_failed} duplicate merges failed, " \
              "{number_of_duplicates_could_not_process} could not be processed because 3 exist " \
              "".format(election_id=google_civic_election_id,
                        number_of_duplicate_candidates_processed=number_of_duplicate_candidates_processed,
                        number_of_duplicate_candidates_failed=number_of_duplicate_candidates_failed,
                        number_of_duplicates_could_not_process=number_of_duplicates_could_not_process)

    messages.add_message(request, messages.INFO, message)

    return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)) +
                                "?google_civic_election_id={var}".format(
                                var=google_civic_election_id))


@login_required
def remove_duplicate_candidate_view(request):
    """
    We use this view to semi-automate the process of finding candidate duplicates. Exact
    copies can be deleted automatically, and similar entries can be manually reviewed and deleted.
    :param request:
    :return:
    """
    authority_required = {'admin'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    google_civic_election_id = request.GET.get('google_civic_election_id', 0)
    candidate_id = request.GET.get('candidate_id', 0)

    remove_duplicate_process = request.GET.get('remove_duplicate_process', False)

    missing_variables = False

    if not positive_value_exists(google_civic_election_id):
        messages.add_message(request, messages.ERROR, "Google Civic Election ID required.")
        missing_variables = True
    if not positive_value_exists(candidate_id):
        messages.add_message(request, messages.ERROR, "Candidate ID required.")
        missing_variables = True

    if missing_variables:
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) + "?google_civic_election_id={var}"
                                                                                   "".format(
            var=google_civic_election_id))

    candidate_campaign_list_manager = CandidateCampaignListManager()
    results = candidate_campaign_list_manager.remove_duplicate_candidate(candidate_id, google_civic_election_id)
    if results['success']:
        if remove_duplicate_process:
            # Continue this process
            return HttpResponseRedirect(reverse('candidate:find_and_remove_duplicate_candidates', args=()) +
                                        "?google_civic_election_id=" + google_civic_election_id)
        else:
            messages.add_message(request, messages.ERROR, results['status'])
            return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))
    else:
        messages.add_message(request, messages.ERROR, "Could not remove candidate {candidate_id} '{candidate_name}'."
                                                      "".format(candidate_id=candidate_id,
                                                                candidate_name=candidate_id))  # TODO Add candidate_name
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) + "?google_civic_election_id={var}"
                                                                                   "".format(
            var=google_civic_election_id))


@login_required
def retrieve_candidate_photos_for_election_view(request, election_id):
    authority_required = {'admin'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_list = []
    google_civic_election_id = convert_to_int(election_id)

    # We only want to process if a google_civic_election_id comes in
    if not positive_value_exists(google_civic_election_id):
        messages.add_message(request, messages.ERROR, "Google Civic Election ID required.")
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()))

    try:
        candidate_list = CandidateCampaign.objects.order_by('candidate_name')
        if positive_value_exists(google_civic_election_id):
            candidate_list = candidate_list.filter(google_civic_election_id=google_civic_election_id)
    except CandidateCampaign.DoesNotExist:
        pass

    display_messages_per_candidate = False
    force_retrieve = False
    num_candidates_reviewed = 0
    num_with_vote_smart_ids = 0
    num_candidates_just_retrieved = 0

    num_with_vote_smart_photos = 0
    num_candidate_photos_just_retrieved = 0

    message = "About to loop through all of the candidates in this election and retrieve photos."
    print_to_log(logger, exception_message_optional=message)

    # Loop through all of the candidates in this election
    for we_vote_candidate in candidate_list:
        num_candidates_reviewed += 1
        retrieve_candidate_results = retrieve_candidate_photos(we_vote_candidate, force_retrieve)
        if retrieve_candidate_results['vote_smart_candidate_exists']:
            num_with_vote_smart_ids += 1
        if retrieve_candidate_results['vote_smart_candidate_just_retrieved']:
            num_candidates_just_retrieved += 1

        if retrieve_candidate_results['vote_smart_candidate_photo_exists']:
            num_with_vote_smart_photos += 1
        if retrieve_candidate_results['vote_smart_candidate_photo_just_retrieved']:
            num_candidate_photos_just_retrieved += 1

        if retrieve_candidate_results['status'] and display_messages_per_candidate:
            messages.add_message(request, messages.INFO, retrieve_candidate_results['status'])

    message = "Google Civic Election ID: {election_id}, " \
              "{num_candidates_reviewed} candidates reviewed, " \
              "{num_with_vote_smart_ids} with Vote Smart Ids, " \
              "{num_candidates_just_retrieved} candidates just retrieved, " \
              "{num_with_vote_smart_photos} with Vote Smart Photos, and " \
              "{num_candidate_photos_just_retrieved} photos just retrieved.".\
        format(election_id=google_civic_election_id,
               num_candidates_reviewed=num_candidates_reviewed,
               num_with_vote_smart_ids=num_with_vote_smart_ids,
               num_candidates_just_retrieved=num_candidates_just_retrieved,
               num_with_vote_smart_photos=num_with_vote_smart_photos,
               num_candidate_photos_just_retrieved=num_candidate_photos_just_retrieved)

    print_to_log(logger, exception_message_optional=message)
    messages.add_message(request, messages.INFO, message)

    return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) + "?google_civic_election_id={var}".format(
        var=google_civic_election_id))


@login_required
def candidate_summary_view(request, candidate_id):
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    messages_on_stage = get_messages(request)
    candidate_id = convert_to_int(candidate_id)
    candidate_on_stage_found = False
    candidate_on_stage = CandidateCampaign()
    try:
        candidate_on_stage = CandidateCampaign.objects.get(id=candidate_id)
        candidate_on_stage_found = True
    except CandidateCampaign.MultipleObjectsReturned as e:
        handle_record_found_more_than_one_exception(e, logger=logger)
    except CandidateCampaign.DoesNotExist:
        # This is fine, create new
        pass

    if candidate_on_stage_found:
        template_values = {
            'messages_on_stage': messages_on_stage,
            'candidate': candidate_on_stage,
        }
    else:
        template_values = {
            'messages_on_stage': messages_on_stage,
        }
    return render(request, 'candidate/candidate_summary.html', template_values)


@login_required
def candidate_delete_process_view(request):
    """
    Delete this candidate
    :param request:
    :return:
    """
    authority_required = {'verified_volunteer'}  # admin, verified_volunteer
    if not voter_has_authority(request, authority_required):
        return redirect_to_sign_in_page(request, authority_required)

    candidate_id = convert_to_int(request.GET.get('candidate_id', 0))
    google_civic_election_id = request.GET.get('google_civic_election_id', 0)

    # Retrieve this candidate
    candidate_on_stage_found = False
    candidate_on_stage = CandidateCampaign()
    if positive_value_exists(candidate_id):
        try:
            candidate_query = CandidateCampaign.objects.filter(id=candidate_id)
            if len(candidate_query):
                candidate_on_stage = candidate_query[0]
                candidate_on_stage_found = True
        except Exception as e:
            messages.add_message(request, messages.ERROR, 'Could not find candidate -- exception.')

    if not candidate_on_stage_found:
        messages.add_message(request, messages.ERROR, 'Could not find candidate.')
        return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) +
                                    "?google_civic_election_id=" + str(google_civic_election_id))

    # Are there any positions attached to this candidate that should be moved to another
    # instance of this candidate?
    position_list_manager = PositionListManager()
    retrieve_public_positions = True  # The alternate is positions for friends-only
    position_list = position_list_manager.retrieve_all_positions_for_candidate_campaign(retrieve_public_positions, candidate_id)
    if positive_value_exists(len(position_list)):
        positions_found_for_this_candidate = True
    else:
        positions_found_for_this_candidate = False

    try:
        if not positions_found_for_this_candidate:
            # Delete the candidate
            candidate_on_stage.delete()
            messages.add_message(request, messages.INFO, 'Candidate Campaign deleted.')
        else:
            messages.add_message(request, messages.ERROR, 'Could not delete -- '
                                                          'positions still attached to this candidate.')
            return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))
    except Exception as e:
        messages.add_message(request, messages.ERROR, 'Could not delete candidate -- exception.')
        return HttpResponseRedirect(reverse('candidate:candidate_edit', args=(candidate_id,)))

    return HttpResponseRedirect(reverse('candidate:candidate_list', args=()) +
                                "?google_civic_election_id=" + str(google_civic_election_id))
